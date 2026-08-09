"""Local HTTP receiver for WhatsApp Web messages captured live.

Companion to tools/live_capture.js.

Runs on 127.0.0.1:8765. Chrome (running on your Mac) POSTs each new
WhatsApp Web message here as JSON. We append it to a WhatsApp-export-
formatted text file so the existing parser can consume it. Every
REFRESH_INTERVAL_MIN minutes, we auto-run refresh.py so the DB stays
current — you never have to touch anything after setup.

Usage:
    python3 tools/live_receiver.py                    # default: WDG
    python3 tools/live_receiver.py --market wdg       # explicit
    python3 tools/live_receiver.py --port 8765

Stop with Ctrl+C. Data is persisted between runs (append-only file).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from paths import exports_dir  # noqa: E402


# ----- Config -----
DEFAULT_PORT = 8765
REFRESH_INTERVAL_MIN = 15   # auto-run refresh.py this often
ALLOWED_ORIGIN = "https://web.whatsapp.com"


class State:
    """Shared state between HTTP handler and background refresher."""
    def __init__(self, market: str):
        self.market = market
        self.out_dir = exports_dir(market)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # Rotate file daily so weekly-refresh workflows still work
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.out_file = self.out_dir / f"live_{self.today}_export.txt"
        # In-memory dedup: (posted_at, sender, text_key) → seen
        self.seen: set[tuple[str, str, str]] = set()
        # Prime seen from existing file so restarts don't re-append
        self._prime_seen()
        self.received_count = 0
        self.new_since_refresh = 0
        self.last_refresh_at: datetime | None = None

    def _prime_seen(self):
        if not self.out_file.exists():
            return
        # Each line is a WhatsApp export line — extract key for dedup
        import re
        header = re.compile(
            r"^\[(\d{2}/\d{2}/\d{4}\s\d{2}:\d{2}:\d{2})\]\s([^:]+):\s?(.*)$"
        )
        for line in self.out_file.read_text(encoding="utf-8").splitlines():
            m = header.match(line)
            if m:
                dt, sender, rest = m.groups()
                self.seen.add((dt, sender.strip(), rest[:80]))
        print(f"[receiver] primed {len(self.seen)} existing messages from {self.out_file.name}")

    def rotate_if_new_day(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.today:
            self.today = today
            self.out_file = self.out_dir / f"live_{self.today}_export.txt"
            print(f"[receiver] rotated to {self.out_file.name}")

    def append(self, date: str, time_s: str, sender: str, text: str) -> bool:
        """Append one message. Returns True if new, False if duplicate."""
        self.rotate_if_new_day()
        # Time may be HH:MM (no seconds); pad to HH:MM:SS
        if time_s.count(":") == 1:
            time_s = f"{time_s}:00"
        dt = f"{date} {time_s}"
        key = (dt, sender, text[:80])
        if key in self.seen:
            return False
        self.seen.add(key)
        line = f"[{dt}] {sender}: {text}\n"
        with self.out_file.open("a", encoding="utf-8") as f:
            f.write(line)
        self.received_count += 1
        self.new_since_refresh += 1
        return True


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            # Simple status endpoint
            if self.path == "/status":
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                body = json.dumps({
                    "ok": True,
                    "market": state.market,
                    "received_total": state.received_count,
                    "new_since_last_refresh": state.new_since_refresh,
                    "last_refresh_at": (
                        state.last_refresh_at.isoformat()
                        if state.last_refresh_at else None
                    ),
                    "output_file": state.out_file.name,
                })
                self.wfile.write(body.encode())
                return
            self.send_response(404)
            self._cors()
            self.end_headers()

        def do_POST(self):
            if self.path != "/msg":
                self.send_response(404)
                self._cors()
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self.send_response(400)
                self._cors()
                self.end_headers()
                return

            # Accept either single message or batch of messages
            items = data if isinstance(data, list) else [data]
            added = 0
            for item in items:
                try:
                    if state.append(item["date"], item["time"], item["sender"], item["text"]):
                        added += 1
                except (KeyError, TypeError):
                    continue

            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"added": added}).encode())

        def log_message(self, format, *args):
            # Silence default HTTP logging (too noisy). Real events are
            # logged from run_refresh_loop and append().
            pass

    return Handler


def _run(cmd, cwd=ROOT, timeout=90):
    """Run a shell command and return (returncode, combined_output)."""
    r = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def auto_git_push(market: str) -> str | None:
    """Commit + push the market's DB if it changed. Returns a short status
    string for logging, or None on no-op. Silently tolerates git errors
    (no network, auth prompt) so the receiver keeps running.
    """
    # Add the whole data/ dir and let git figure out which .db files changed
    try:
        # Anything to commit?
        rc, _ = _run(["git", "diff", "--quiet", "--", "data/"])
        if rc == 0:
            return None  # nothing changed
        rc, out = _run(["git", "add", "data/"])
        if rc != 0:
            return f"git add failed: {out[:120]}"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        rc, out = _run([
            "git", "commit", "-q", "-m",
            f"live: {market} refresh {stamp}",
        ])
        if rc != 0:
            return f"git commit failed: {out[:120]}"
        rc, out = _run(["git", "push", "-q"], timeout=60)
        if rc != 0:
            return f"git push failed: {out[:120]}"
        return "pushed"
    except subprocess.TimeoutExpired:
        return "git operation timed out"
    except Exception as e:
        return f"git error: {e}"


def run_refresh_loop(state: State, interval_min: int, do_push: bool):
    """Background thread: run refresh.py every interval_min minutes if there
    are new messages since the last refresh, then optionally git-push so
    Streamlit Cloud picks up the changes."""
    while True:
        time.sleep(interval_min * 60)
        if state.new_since_refresh == 0:
            continue
        n = state.new_since_refresh
        print(f"[refresh] {n} new messages → running refresh.py --market {state.market}")
        state.new_since_refresh = 0
        try:
            subprocess.run(
                [sys.executable, str(ROOT / "src" / "refresh.py"),
                 "--market", state.market],
                cwd=ROOT, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=300,
            )
            state.last_refresh_at = datetime.now()
            print(f"[refresh] done at {state.last_refresh_at.strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[refresh] error: {e}")
            continue

        # Push to GitHub so the Streamlit Cloud app sees the new data
        if do_push:
            status = auto_git_push(state.market)
            if status == "pushed":
                print(f"[git] pushed at {datetime.now().strftime('%H:%M:%S')} — Streamlit will redeploy shortly")
            elif status is None:
                pass  # nothing to commit — silent
            else:
                print(f"[git] {status}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="wdg", help="Which market DB to feed")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--refresh-min", type=int, default=REFRESH_INTERVAL_MIN,
                    help="Auto-run refresh.py this often (min)")
    ap.add_argument("--no-push", action="store_true",
                    help="Skip the automatic git push after each refresh")
    args = ap.parse_args()

    state = State(args.market)
    handler = make_handler(state)
    server = HTTPServer(("127.0.0.1", args.port), handler)

    do_push = not args.no_push
    # Background refresh loop
    t = threading.Thread(
        target=run_refresh_loop, args=(state, args.refresh_min, do_push),
        daemon=True,
    )
    t.start()

    print(f"[receiver] listening on http://127.0.0.1:{args.port}")
    print(f"[receiver] market={args.market}  writing to {state.out_file}")
    print(f"[receiver] auto-refresh every {args.refresh_min} min"
          f"{' + git push' if do_push else ' (no auto-push)'}")
    print(f"[receiver] status: http://127.0.0.1:{args.port}/status")
    print(f"[receiver] Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[receiver] stopping")


if __name__ == "__main__":
    main()
