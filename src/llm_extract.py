"""Claude API fallback for lines the regex parser couldn't handle.

Sends batches of unparsed candidate lines to Claude with a strict JSON schema
and produces Listing objects we can insert alongside regex-parsed ones.

Requires:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
"""

from __future__ import annotations

import json
import os
from typing import Iterable

from parser import Listing


SYSTEM_PROMPT = """You extract structured watch-listing data from messy WhatsApp chat lines from a Hong Kong watch dealer group.

For each line, output one JSON object per watch listed in that line. Most lines have ONE watch. A line that does not actually list a watch for sale should output an empty array.

Fields:
- brand: full brand name (e.g. "Patek Philippe", "Rolex", "Audemars Piguet", "Vacheron Constantin", "Richard Mille", "Cartier", "A. Lange & Söhne", "Omega", "Hublot", "IWC", "Panerai", "H. Moser", "Roger Dubuis", "Tag Heuer", "Tudor", "Bvlgari", "Parmigiani", "Breguet"). null if you can't tell.
- reference: model reference exactly as listed (e.g. "5167R", "126234", "4520V/210A-B128", "26240ST.OO.1320ST.05"). Preserve hyphens and slashes.
- dial_color: dial color or material descriptor in lowercase (e.g. "blue", "black", "salmon", "tiffany", "ice blue", "rose gold", "platinum"). null if unspecified.
- year_made: 4-digit year the watch was made (e.g. 2022). null if unspecified. Do NOT use the year the message was posted.
- month_made: 1-12 if the listing specifies a month (e.g. "N5/26" = month 5). null otherwise.
- condition: "new" or "used". null if unspecified.
- full_set: true if "full set" / "fullset" mentioned, false if "naked" / "watch only", null otherwise.
- price_hkd: integer price in HKD. Convert "K" suffix to ×1000, "M"/"mil" to ×1000000. null if not given in HKD.
- price_usdt: integer price in USDT/USD. null if not given.

Output a JSON array. No prose, no markdown fences. Example:
Input line: "✨New 4520V/210A-B128 2026 HKD:261K"
Output: [{"brand":"Vacheron Constantin","reference":"4520V/210A-B128","dial_color":null,"year_made":2026,"month_made":null,"condition":"new","full_set":null,"price_hkd":261000,"price_usdt":null}]
"""


def _build_user_prompt(items: list[dict]) -> str:
    parts = ["Extract watch listings from these lines. Return one JSON array per line, in the same order.\n"]
    for i, item in enumerate(items):
        parts.append(f"\n--- Line {i+1} ---")
        if item.get("message_context"):
            parts.append(f"Context (truncated): {item['message_context'][:200]}")
        parts.append(f"Line: {item['line']}")
    parts.append("\nReturn a single JSON object: {\"results\": [<array-for-line-1>, <array-for-line-2>, ...]}")
    return "\n".join(parts)


def extract_with_llm(
    unparsed: Iterable[dict],
    *,
    source_file: str,
    batch_size: int = 25,
    model: str = "claude-haiku-4-5-20251001",
    max_lines: int | None = None,
) -> list[Listing]:
    """Call Claude on unparsed lines and return Listing objects it produces.

    Uses Haiku 4.5 by default — fast and cheap, sufficient for structured extraction.
    """
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic package not installed. Run: pip install anthropic"
        ) from e

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY env var not set. Export it before running with --llm."
        )

    client = anthropic.Anthropic()
    items = list(unparsed)
    if max_lines:
        items = items[:max_lines]

    listings: list[Listing] = []
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        user_prompt = _build_user_prompt(batch)

        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = resp.content[0].text.strip()
        # Strip code fences if Claude added any
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        try:
            parsed = json.loads(text)
            results = parsed.get("results", [])
        except json.JSONDecodeError as e:
            print(f"  · LLM batch {i//batch_size + 1}: JSON parse failed ({e})")
            continue

        for src, watches in zip(batch, results):
            if not isinstance(watches, list):
                continue
            for w in watches:
                if not isinstance(w, dict) or not w.get("reference"):
                    continue
                listings.append(Listing(
                    posted_at=src["posted_at"],
                    seller=src.get("seller", "") or "",
                    brand=w.get("brand"),
                    reference=str(w["reference"]).upper(),
                    dial_color=w.get("dial_color"),
                    year_made=w.get("year_made"),
                    month_made=w.get("month_made"),
                    condition=w.get("condition"),
                    price_hkd=w.get("price_hkd"),
                    price_usdt=w.get("price_usdt"),
                    full_set=w.get("full_set"),
                    raw_line=src["line"],
                    raw_message=src.get("message_context", "")[:500],
                    source_file=source_file,
                    confidence="llm",
                ))
    return listings
