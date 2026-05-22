"""WhatsApp export parser for HK watch market price lists.

Reads a WhatsApp `_chat.txt` export and emits one dict per watch listing.

Each input message is split into individual lines; each line is tested against
a set of heuristics to decide whether it represents a price listing. Lines we
can't confidently parse are surfaced in `unparsed_lines()` so they can be sent
to an LLM fallback (see llm_extract.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator


MESSAGE_HEADER = re.compile(
    r"^‎?\[(\d{2}/\d{2}/\d{4})\s(\d{2}:\d{2}:\d{2})\]\s([^:]+):\s?(.*)$"
)

WTB_KEYWORDS = (
    "looking for", "looking", "wtb", "want to buy", "需要", "wanted",
    "need ", "search for", "searching", "best offer",
)

SYSTEM_HINTS = (
    "image absente", "vidéo absente", "audio absent", "sticker absent",
    "messages sont chiffrés", "en attente de ce message", "messages éphémères",
    "a ajouté", "a supprimé", "a créé ce groupe", "a utilisé un lien",
    "vous avez rejoint", "a changé",
)

CONDITION_PATTERNS = [
    (re.compile(r"\b(brand[- ]?new|unworn|unused)\b", re.I), "new"),
    (re.compile(r"\b(new|n(?:ew)?[\s/]?stock|✨new|💓new|🆕)\b", re.I), "new"),
    (re.compile(r"\b(used|usd|like new|fullset.*used|secondhand|2nd hand|pre[- ]?owned)\b", re.I), "used"),
    (re.compile(r"\bnaked\b", re.I), "used"),
]

# Price patterns. Order matters: try most specific first.
# Match things like: HKD415K, HKD:236K, HKD 192000, 900000HKD, 115000USDT,
# $113,000, 1.95mil, 1.2M, 098k, hkd2.5m
PRICE_RE = re.compile(
    r"""
    (?P<currency1>HKD|USDT|USD|\$)?\s*:?\s*
    (?P<amount>\d[\d,\.]*)
    \s*
    (?P<suffix>k|K|m|M|mil|MIL)?
    \s*
    (?P<currency2>HKD|USDT|USD|hkd|usdt|usd)?
    """,
    re.VERBOSE,
)

# References we want to extract. These cover most major brands by reference shape.
# We try the strictest first, fall back to looser patterns.
REFERENCE_PATTERNS = [
    # Vacheron Constantin: 4520V/210A-B128, 7930v/210t-h074, 4307V/220G-236C, 44600V/200R-B979
    re.compile(r"\b(\d{4,5}[A-Z]/\d{3,4}[A-Z0-9]-[A-Z]?\d{3}[A-Z]?)\b", re.I),
    re.compile(r"\b(\d{4,5}[A-Z]/\d{3,4}[A-Z0-9])\b", re.I),
    # VC with slash but no letter prefix: 43175/000R-9687
    re.compile(r"\b(\d{4,5}/\d{3,4}[A-Z]?-\d{3,4}[A-Z]?)\b", re.I),
    # AP dot refs: 26240ST.OO.1320ST.05, 15407ST.OO.1220ST.01
    re.compile(r"\b(\d{4,5}[A-Z]{2}\.[A-Z0-9]{2,4}\.[A-Z0-9]{4,8}\.\d{2})\b", re.I),
    # Patek slashed: 5160/500G, 5167/1A, 5712/1A, 5990/1R, 7118/1200R, 5719/10G
    re.compile(r"\b(\d{4}/\d{1,4}[A-Z]{1,3}(?:-\d{3})?)\b", re.I),
    # Breguet hyphenated: 3661B-1954-55A, 5817BR-12-9V8, 7027BR-G9-9V6
    re.compile(r"\b(\d{4}[A-Z]{1,2}-\d{1,4}-\d{1,3}[A-Z0-9]{0,3})\b", re.I),
    # AP, Patek, VC short: 26240ST, 5167R, 5711P, 15400OR, 77450BC, 89000
    re.compile(r"\b(\d{4,5}[A-Z]{1,3}(?:-\d{3,4})?)\b", re.I),
    # Cartier HPI / Vacheron VCARO etc
    re.compile(r"\b(HPI\d{5})\b", re.I),
    re.compile(r"\b(VCARO\d{5,6})\b", re.I),
    re.compile(r"\b(G0A\d{4,6})\b", re.I),
    # AP/RM with hyphen suffix: RM030-01, 116503-0001
    re.compile(r"\b(\d{6}-\d{4})\b"),
    # Omega 234.30.41.21.01.001 (must come before Lange 3.3 pattern)
    re.compile(r"\b(\d{3}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{3})\b"),
    # A. Lange: 101.027, 405.035, 232.026 (negative-lookahead so it doesn't eat Omega's prefix)
    re.compile(r"\b(\d{3}\.\d{3})(?!\d|\.)"),
    # Rolex: 126234, 126503, 116503, 336938, 277200, 116505-0001
    re.compile(r"\b(1\d{5}[A-Z]{0,5}(?:-\d{4})?)\b", re.I),
    re.compile(r"\b(2\d{5}[A-Z]{0,5}(?:-\d{4})?)\b", re.I),
    re.compile(r"\b(3\d{5}[A-Z]{0,5})\b", re.I),
    # Richard Mille: RM055, RM 030, RM30-01, RM65-01, RM72-01
    re.compile(r"\b(RM\s?\d{2,3}(?:[- ]\d{2})?)\b", re.I),
    # Cartier WJTA0037 / W4PN0016 / W6920097 / WB520003 / W2020033
    re.compile(r"\b(W[A-Z0-9]{6,8})\b"),
    # Cartier internal numeric: 31030425001004 (14 digits)
    re.compile(r"\b(\d{14})\b"),
    # Hermès short: H6951, H5696
    re.compile(r"\b(H\d{4,5})\b"),
    # Hublot 909.QDW.1120.RX
    re.compile(r"\b(\d{3}\.[A-Z]{2,3}\.\d{4}\.[A-Z]{2,3}(?:\.[A-Z0-9]+)?)\b"),
    # IWC IW503203
    re.compile(r"\b(IW\d{5,6})\b", re.I),
    # Panerai Pam00914
    re.compile(r"\b(Pam\d{5})\b", re.I),
    # Patek/AP/etc generic 4 digit (must have a letter or slash nearby — avoid grabbing prices)
    re.compile(r"\b(\d{4})(?=[A-Za-z/])"),
]

# Year-made hints. Be STRICT — hyphens count as alphanumeric so ref-internal
# digits (e.g. "1954" in "3661B-1954-55A") aren't grabbed. But allow an
# optional `y`/`Y`/`year` shorthand suffix (dealers often write `2021y`).
YEAR_RE = re.compile(
    r"(?<![\w/\-])(19[89]\d|20[0-3]\d)"
    r"(?:[Yy]|year|used|new|unworn)?"
    r"(?![\w/\-])",
    re.I,
)
N_DATE_RE = re.compile(r"\bN\s?(\d{1,2})[\.\/](\d{2,4})\b", re.I)  # N5/26 or N1.2026
N_PLAIN_RE = re.compile(r"\bN(\d{1,2})\b(?![\.\/])", re.I)  # N5 (month only, current year)
MONTH_NAME_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-\s]+(\d{4})\b",
    re.I,
)
MONTH_YEAR_RE = re.compile(r"(?<![\w/\-])(\d{1,2})/(\d{4})(?![\w/\-])")  # 1/2026, 12/2024
SHORT_YEAR_MONTH_RE = re.compile(r"(?<![\w/\-])(\d{2})/(\d{1,2})(?![\w/\-])")  # 25/3 = Mar 2025

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Dial colors. Allow multi-word phrases. Listed longest-first so longer
# matches win (e.g. "ice blue" before "blue", "rose gold" before "rose").
COLOR_PHRASES = [
    "salmon pink", "baby pink", "hot pink", "light pink", "dark pink",
    "ice blue", "ice white", "iceblue",
    "rose gold", "yellow gold", "white gold", "champ gold", "champagne",
    "midnight blue", "navy blue", "dark blue", "light blue", "royal blue",
    "racing green", "olive green", "dark green", "light green", "khaki green",
    "tiffany blue", "tiffany",
    "panda", "reverse panda",
    "smoked grey", "fume", "fumé",
    "two tone", "two-tone",
    "diamond pave", "pave", "pavé", "full diamond", "rainbow",
    "salmon", "olive", "khaki", "burgundy", "wine", "tropical", "patina",
    "aventurine", "meteorite", "mother of pearl", "mop",
    "white", "black", "blue", "green", "grey", "gray", "silver", "gold",
    "yellow", "pink", "champ", "brown", "purple", "red", "orange", "ivory",
    "platinum", "steel", "rose", "sky", "diamond", "ceramic", "chocolate",
    "choco", "turquoise", "cream", "anthracite", "bronze", "copper",
    "rg", "wg", "yg", "pt", "rosegold",
]

# Brand inference from reference patterns
def infer_brand(reference: str, message_context: str = "") -> str | None:
    ref = reference.upper()
    ctx = message_context.upper()

    # Strong reference-shape hints first (unambiguous brands)
    if ref.startswith("RM"):
        return "Richard Mille"
    if ref.startswith("IW"):
        return "IWC"
    if ref.startswith("PAM"):
        return "Panerai"
    if ref.startswith("W") and re.match(r"^W[A-Z]{2,3}\d{4,5}$", ref):
        return "Cartier"
    if re.match(r"^\d{3}\.\d{3}$", ref):
        return "A. Lange & Söhne"
    if re.match(r"^\d{3}\.\d{2}\.\d{2}", ref):
        return "Omega"
    if re.match(r"^\d{4,5}[A-Z]/", ref):
        return "Vacheron Constantin"
    # AP dot-notation
    if "." in ref and re.match(r"^\d{4,5}[A-Z]{2}\.", ref):
        return "Audemars Piguet"
    # AP shorthand: 26240OR, 15510ST, 77450BC, 16202BA — distinctive 5-digit + 2 letters
    # (must come before context hints, since one message can mix brands)
    if re.match(
        r"^(?:152|154|155|158|162|167|172|252|258|259|262|263|264|265|266|267|268|274|275|276|277|484|664|774|775|774)\d{2}[A-Z]{2}",
        ref,
    ):
        return "Audemars Piguet"
    # Rolex 6-digit (unambiguous)
    if re.match(r"^[123]\d{5}[A-Z]{0,5}(?:-\d{4})?$", ref):
        return "Rolex"

    # Message-context hints (group headers like "PP", "AP", "VC", etc.)
    # Highest signal first; tested in order.
    brand_hints = [
        ("👑", "Patek Philippe"),   # Miss uses crown for PP
        ("🛡️", "Vacheron Constantin"),  # Miss uses shield for VC
        ("🛰️", "Audemars Piguet"),     # Miss uses satellite for AP
        ("🏕️", "Audemars Piguet"),     # AP new stock variant
        ("VC USED STOCK", "Vacheron Constantin"),
        ("VC NEW STOCK", "Vacheron Constantin"),
        ("PP USED STOCK", "Patek Philippe"),
        ("PP NEW STOCK", "Patek Philippe"),
        ("AP STOCK", "Audemars Piguet"),
        ("AP USED", "Audemars Piguet"),
        ("AP NEW", "Audemars Piguet"),
        ("VACHERON", "Vacheron Constantin"),
        ("PATEK", "Patek Philippe"),
        ("AUDEMARS", "Audemars Piguet"),
        ("ROLEX", "Rolex"),
        ("HUBLOT", "Hublot"),
        ("RICHARD MILLE", "Richard Mille"),
        ("CARTIER", "Cartier"),
        ("A. LANGE", "A. Lange & Söhne"),
        ("LANGE", "A. Lange & Söhne"),
        ("OMEGA", "Omega"),
        ("IWC", "IWC"),
        ("BREGUET", "Breguet"),
        ("PANERAI", "Panerai"),
        ("MOSER", "H. Moser"),
        ("PARMIGIANI", "Parmigiani"),
        ("ROGER DUBUIS", "Roger Dubuis"),
        ("TAG HEUER", "Tag Heuer"),
        ("TUDOR", "Tudor"),
        ("BVLGARI", "Bvlgari"),
    ]
    for hint, brand in brand_hints:
        if hint in ctx:
            return brand

    # Fall back to reference shape
    if re.match(r"^[123]\d{5}", ref):
        return "Rolex"
    # Patek: 4-digit
    if re.match(r"^[45-7]\d{3}", ref):
        return "Patek Philippe"
    return None


@dataclass
class Listing:
    posted_at: str  # ISO datetime
    seller: str
    brand: str | None
    reference: str
    dial_color: str | None
    year_made: int | None
    month_made: int | None  # for "N5/26" style; otherwise None
    condition: str | None  # 'new', 'used', 'unworn'
    price_hkd: int | None
    price_usdt: int | None
    full_set: bool | None
    raw_line: str           # original line (with emojis) for verification
    raw_message: str = ""
    source_file: str = ""
    confidence: str = "regex"  # 'regex' or 'llm'
    clean_line: str = ""    # emoji-stripped, normalized for display


def format_month(year: int | None, month: int | None) -> str:
    """Display year/month as 'N6/26', 'N1/26', or just '2024'.

    The 'N' prefix indicates a sale-month indicator (typical dealer notation
    for 'new delivered in MM/YY'). When only a year is known, returns the
    plain year.
    """
    if month and year:
        return f"N{month}/{str(year)[-2:]}"
    if year:
        return str(year)
    if month:
        return f"N{month}"
    return ""


def parse_price(text: str) -> tuple[int | None, int | None]:
    """Return (hkd, usdt) from a chunk of text. Either may be None."""
    text = text.replace(",", "").replace(" ", "")
    hkd = None
    usdt = None

    # Walk every numeric match, attach to currency context
    # Look for patterns like 900000HKD, HKD:236K, 115000USDT, $113000, 1.95mil
    matches = list(re.finditer(
        r"(?P<cur1>HKD|USDT|USD|\$)?\s*:?\s*"
        r"(?P<amt>\d+(?:\.\d+)?)\s*"
        r"(?P<suf>k|m|mil)?"
        r"\s*(?P<cur2>HKD|USDT|USD|hkd|usdt|usd)?",
        text, re.I,
    ))
    for m in matches:
        amt_str = m.group("amt")
        if not amt_str:
            continue
        try:
            amt = float(amt_str)
        except ValueError:
            continue
        suf = (m.group("suf") or "").lower()
        if suf == "k":
            amt *= 1_000
        elif suf in ("m", "mil"):
            amt *= 1_000_000
        # Skip lone tiny numbers that are years or sizes
        if amt < 1000:
            continue
        cur = (m.group("cur1") or m.group("cur2") or "").upper().replace("$", "USD")
        if cur == "USDT":
            usdt = int(amt)
        elif cur == "USD":
            # Treat $ in HK lists as HKD if no other HKD context; else USD ≈ USDT
            usdt = int(amt) if usdt is None else usdt
        else:
            # Default to HKD if no currency given (this is an HK price list)
            hkd = int(amt) if hkd is None else hkd
    return hkd, usdt


def extract_price(line: str) -> tuple[int | None, int | None, str]:
    """Extract price and return (hkd, usdt, matched_chunk)."""
    # Greedy: look for explicit HKD/USDT/$ markers first
    pats = [
        re.compile(r"(?:HKD|hkd)\s*:?\s*(\d+(?:[\.,]\d+)?)\s*(k|m|mil)?", re.I),
        re.compile(r"(\d+(?:[\.,]\d+)?)\s*(k|m|mil)?\s*(?:HKD|hkd)", re.I),
        re.compile(r"(?:USDT|usdt)\s*:?\s*(\d+(?:[\.,]\d+)?)\s*(k|m|mil)?", re.I),
        re.compile(r"(\d+(?:[\.,]\d+)?)\s*(k|m|mil)?\s*(?:USDT|usdt)", re.I),
        re.compile(r"\$\s*(\d+(?:[\.,]\d+)?)\s*(k|m|mil)?", re.I),
        re.compile(r"💰\s*(\d+(?:[\.,]\d+)?)\s*(k|m|mil)?", re.I),
        re.compile(r"price[\s:]+(\d+(?:[\.,]\d+)?)\s*(k|m|mil)?", re.I),
    ]
    hkd = None
    usdt = None
    for pat in pats:
        for m in pat.finditer(line):
            amt_str = m.group(1).replace(",", "")
            try:
                amt = float(amt_str)
            except ValueError:
                continue
            suf = (m.group(2) or "").lower()
            if suf == "k":
                amt *= 1_000
            elif suf in ("m", "mil"):
                amt *= 1_000_000
            elif amt < 1000:
                # Bare number under 1000 is probably not a price unless followed by k/m
                continue
            pat_src = pat.pattern.lower()
            # In HK dealer lists "$" means HKD, not USD/USDT. Only the
            # explicit USDT keyword represents the crypto stablecoin price.
            if "usdt" in pat_src:
                if usdt is None:
                    usdt = int(amt)
            else:
                if hkd is None:
                    hkd = int(amt)
    # Fallback 1: a bare `<num>k` or `<num>m` suffix (no currency word) — these
    # are HKD by default in HK price lists. e.g. "ref Black 2024 720k"
    if hkd is None and usdt is None:
        # Find numbers that aren't part of a reference (no letter immediately
        # before the digits). Restrict to numbers followed by k/m at line/word end.
        for m in re.finditer(
            r"(?<![A-Za-z\-/])(\d+(?:[\.,]\d+)?)\s*([kKmM]|mil|MIL)\b",
            line,
        ):
            amt_str = m.group(1).replace(",", "")
            try:
                amt = float(amt_str)
            except ValueError:
                continue
            suf = m.group(2).lower()
            if suf == "k":
                amt *= 1_000
            else:
                amt *= 1_000_000
            if amt >= 5000:
                hkd = int(amt)
                break

    # Fallback 2: a 5-7 digit integer near the end of the line (likely an
    # un-suffixed HKD price like "168000 HKD" or "150,000")
    if hkd is None and usdt is None:
        # Search ONLY in the second half of the line — refs are at the start
        half = max(len(line) // 2, 1)
        for m in re.finditer(r"\b(\d{5,7})\b", line[half:]):
            amt = int(m.group(1))
            if 5000 <= amt <= 50_000_000:
                hkd = amt
                break
    return hkd, usdt, line


def extract_condition(line: str) -> tuple[str | None, bool | None]:
    """Return (condition, full_set)."""
    full_set = None
    lo = line.lower()
    if "full set" in lo or "fullset" in lo:
        full_set = True
    if "naked" in lo or "watch only" in lo or "watch+paper" in lo:
        full_set = False
    for pat, cond in CONDITION_PATTERNS:
        if pat.search(line):
            return cond, full_set
    return None, full_set


def extract_year_month(line: str) -> tuple[int | None, int | None]:
    """Extract year-made and month from the listing line.

    Handles (in order of precedence):
      - N5/26, n1.2026   → new + month + year
      - Jan-2026, Feb 2024 → month name + year
      - 1/2026, 12/2024  → month/year
      - 25/3, 24/11      → year/month (yy/mm)
      - 2024, 2024y      → bare year (only if not adjacent to hyphens/letters)

    Critically: ref-internal digits like the "1954" in "3661B-1954-55A" are
    NOT treated as years thanks to strict word-boundary lookarounds.
    """
    # 1. N5/26 form (new + month + year)
    m = N_DATE_RE.search(line)
    if m:
        month = int(m.group(1))
        ystr = m.group(2)
        year = int(ystr) + 2000 if len(ystr) == 2 else int(ystr)
        if 1 <= month <= 12 and 1990 <= year <= 2040:
            return year, month

    # 2. Month-name form: Jan-2026, Feb 2024
    m = MONTH_NAME_RE.search(line)
    if m:
        month = MONTH_MAP[m.group(1).lower()[:3]]
        year = int(m.group(2))
        return year, month

    # 3. month/year form: 1/2026, 12/2024 (where the 4-digit side is the year)
    m = MONTH_YEAR_RE.search(line)
    if m:
        month = int(m.group(1))
        year = int(m.group(2))
        if 1 <= month <= 12 and 1990 <= year <= 2040:
            return year, month

    # 4. short yy/mm form: 25/3, 24/11 → Mar 2025, Nov 2024
    m = SHORT_YEAR_MONTH_RE.search(line)
    if m:
        yy = int(m.group(1))
        mm = int(m.group(2))
        if yy <= 35 and 1 <= mm <= 12:
            return 2000 + yy, mm

    # 5. Bare 4-digit year — strict: not adjacent to digits/letters/hyphens
    m = YEAR_RE.search(line)
    if m:
        return int(m.group(1)), None

    return None, None


def extract_color(line: str) -> str | None:
    """Find the dial color or material descriptor.

    Tries multi-word phrases first ("ice blue", "rose gold") so we don't
    truncate compound colors. Returns the matched phrase as-cased.
    """
    lo = line.lower()
    best: tuple[int, str] | None = None  # (position, phrase)
    for phrase in COLOR_PHRASES:
        # Word-boundary match. For phrases with spaces, the boundary is at
        # the phrase edges; the inner space is literal.
        m = re.search(rf"\b{re.escape(phrase)}\b", lo)
        if m:
            pos = m.start()
            # Prefer the LEFTMOST match. Among ties, longer phrase wins
            # (because COLOR_PHRASES is ordered longest-first within each
            # color family, the first match at the leftmost position will be
            # the longest valid one).
            if best is None or pos < best[0]:
                best = (pos, phrase)
    if best is None:
        return None
    # Title-case for display ("Ice Blue", "Rose Gold")
    return " ".join(w.capitalize() for w in best[1].split())


# Unicode emoji / pictograph ranges. Used to clean raw lines for display.
_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001F6FF"  # symbols & pictographs, transport
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002600-\U000027BF"  # misc symbols & dingbats
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U0000FE0F"             # variation selector
        "‍"                 # ZWJ
        "]+", flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    """Remove emojis and clean up whitespace for human-readable display."""
    cleaned = _EMOJI_RE.sub("", text)
    # Collapse repeated whitespace, strip stray punctuation residue
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    return cleaned


_PRICE_MARKER_RE = re.compile(
    r"(?:HKD|USDT|USD|\$|💰|prix|price|\bprice\b)",
    re.I,
)


def _find_price_region_start(line: str) -> int:
    """Return the index where the price portion of the line starts.

    Refs live before the price; anything after the price marker is treated
    as price noise and ignored during reference extraction.
    """
    m = _PRICE_MARKER_RE.search(line)
    return m.start() if m else len(line)


def extract_reference(line: str) -> str | None:
    """Find the most specific reference, preferring matches BEFORE the price.

    The user noted that the reference is almost always at the start of the
    line; anything that looks like a reference but sits after `HKD`, `USDT`,
    `$`, etc. is much more likely to be a price typo (e.g. `868000hkd`
    matched as `8680`) and is rejected.
    """
    # Strip leading emojis/symbols. Also collapse year-suffix "2022y" → "2022 "
    # so it doesn't get captured as reference "2022Y".
    clean = re.sub(r"^[^\w\d]+", "", line)
    clean = re.sub(r"\b((?:19|20)\d{2})[Yy]\b", r"\1 ", clean)
    price_start = _find_price_region_start(clean)

    best: tuple[int, int, str] | None = None  # (pattern_priority, position, ref)
    for pat_idx, pat in enumerate(REFERENCE_PATTERNS):
        for m in pat.finditer(clean):
            ref = m.group(1).upper()
            pos = m.start()
            # Skip refs that appear inside the price region
            if pos >= price_start:
                continue
            # Reject pure 4-digit years (1990–2030)
            if re.fullmatch(r"(?:19[89]\d|20[0-3]\d)", ref):
                continue
            # Reject leading-zero numerics
            if re.fullmatch(r"\d{5,7}", ref) and ref.startswith("0"):
                continue
            # Prefer the leftmost ref overall; ties broken by pattern priority
            # (earlier patterns are more specific).
            cand = (pos, pat_idx, ref)
            if best is None:
                best = cand
            else:
                # Strict "leftmost wins"; only on equal position prefer specific pattern
                if cand[0] < best[0] or (cand[0] == best[0] and cand[1] < best[1]):
                    best = cand
    return best[2] if best else None


def is_listing_line(line: str) -> bool:
    """Heuristic: does this line look like a price listing?"""
    if not line.strip():
        return False
    lo = line.lower()
    # Skip WTB
    for kw in WTB_KEYWORDS:
        if kw in lo:
            return False
    # Must have a price-ish thing (3+ consecutive digits anywhere)
    if not re.search(r"\d{3,7}", line):
        return False
    # Must have something currency-like or a reference shape
    has_currency = bool(re.search(r"(?:hkd|usdt|usd)\b|\$|💰|\bk\b|\bm\b|mil", line, re.I))
    has_ref = bool(extract_reference(line))
    return has_currency or has_ref


def parse_line(line: str, posted_at: str, seller: str, message_context: str, source_file: str) -> Listing | None:
    # Strip WhatsApp strikethrough (~text~) and HK$ → HKD
    line = line.replace("~", "").replace("HK$", "HKD ")
    if not is_listing_line(line):
        return None
    ref = extract_reference(line)
    if not ref:
        return None
    hkd, usdt, _ = extract_price(line)
    if hkd is None and usdt is None:
        return None
    condition, full_set = extract_condition(line)
    # Condition fallback from context (e.g., "VC New Stock" header above)
    if condition is None:
        ctx_lo = message_context.lower()
        if "new stock" in ctx_lo or "✨new" in ctx_lo or "new patek" in ctx_lo:
            condition = "new"
        elif "used stock" in ctx_lo or "used full set" in ctx_lo:
            condition = "used"
    year, month = extract_year_month(line)
    color = extract_color(line)
    brand = infer_brand(ref, message_context)

    return Listing(
        posted_at=posted_at,
        seller=seller,
        brand=brand,
        reference=ref,
        dial_color=color,
        year_made=year,
        month_made=month,
        condition=condition,
        price_hkd=hkd,
        price_usdt=usdt,
        full_set=full_set,
        raw_line=line.strip(),
        raw_message=message_context[:500],
        source_file=source_file,
        confidence="regex",
        clean_line=strip_emojis(line),
    )


def iter_messages(text: str) -> Iterator[tuple[str, str, str]]:
    """Yield (posted_at_iso, seller, body) per WhatsApp message."""
    current_dt = None
    current_seller = None
    current_body: list[str] = []

    for raw in text.splitlines():
        m = MESSAGE_HEADER.match(raw)
        if m:
            if current_dt is not None:
                yield current_dt, current_seller, "\n".join(current_body)
            date_s, time_s, seller, msg = m.groups()
            try:
                dt = datetime.strptime(f"{date_s} {time_s}", "%d/%m/%Y %H:%M:%S")
                current_dt = dt.isoformat()
            except ValueError:
                current_dt = None
            current_seller = seller.strip().lstrip("~ ").strip()
            current_body = [msg]
        else:
            if current_dt is not None:
                current_body.append(raw)
    if current_dt is not None:
        yield current_dt, current_seller, "\n".join(current_body)


def is_system_message(body: str) -> bool:
    lo = body.lower()
    return any(h in lo for h in SYSTEM_HINTS)


@dataclass
class ParseResult:
    listings: list[Listing] = field(default_factory=list)
    unparsed: list[dict] = field(default_factory=list)  # candidate lines we couldn't parse

    def summary(self) -> str:
        return (
            f"listings={len(self.listings)} "
            f"unparsed_candidates={len(self.unparsed)}"
        )


def parse_export(path: Path) -> ParseResult:
    text = path.read_text(encoding="utf-8")
    result = ParseResult()
    source_file = path.name

    for posted_at, seller, body in iter_messages(text):
        if is_system_message(body):
            continue
        if not body.strip():
            continue
        # Skip pure WTB messages (the whole message starts with looking-for)
        first_line_lo = body.strip().splitlines()[0].lower() if body.strip() else ""
        if any(kw in first_line_lo for kw in ("looking for", "wtb", "[wtb]", "looking")):
            continue
        # First pass: line-by-line parsing
        # Second pass: pair "ref line" + "price line" when split across two lines.
        lines = [ln.strip() for ln in body.splitlines()]
        pending_ref_line: str | None = None  # a line that has a ref but no price
        for line in lines:
            if not line:
                pending_ref_line = None
                continue
            listing = parse_line(line, posted_at, seller or "", body, source_file)
            if listing:
                result.listings.append(listing)
                pending_ref_line = None
                continue

            # Maybe this is a ref-only line (no price) — remember for pairing
            ref = extract_reference(line)
            hkd, usdt, _ = extract_price(line)
            has_price_marker = bool(
                re.search(r"(?:hkd|usdt|usd|💰)", line, re.I) or "$" in line
            )
            if ref and not (hkd or usdt) and not has_price_marker \
                    and not any(kw in line.lower() for kw in WTB_KEYWORDS):
                pending_ref_line = line
                continue

            # Maybe this is a price-only line and we have a pending ref above
            if pending_ref_line and (hkd or usdt or has_price_marker) and not ref:
                combined = f"{pending_ref_line} {line}"
                listing = parse_line(combined, posted_at, seller or "", body, source_file)
                if listing:
                    listing.raw_line = combined
                    result.listings.append(listing)
                    pending_ref_line = None
                    continue

            # Otherwise: candidate for LLM fallback
            if has_price_marker and re.search(r"\d{3,}", line) \
                    and not any(kw in line.lower() for kw in WTB_KEYWORDS):
                result.unparsed.append({
                    "posted_at": posted_at,
                    "seller": seller,
                    "line": line,
                    "message_context": body[:500],
                    "source_file": source_file,
                })
    return result


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("export", type=Path)
    ap.add_argument("--show-unparsed", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    res = parse_export(args.export)
    print(res.summary())
    print("\nSample listings:")
    for l in res.listings[: args.limit]:
        print(json.dumps(asdict(l), ensure_ascii=False))
    if args.show_unparsed:
        print("\nUnparsed candidates (first 30):")
        for u in res.unparsed[:30]:
            print(u["line"])
