#!/usr/bin/env python3
"""Convert SOLIDserver REST API PDF to per-chapter markdown files in api_docs/.

Usage (from repo root):
    pdftotext -layout SOLIDserver_API-Reference_REST-8.4.pdf api_full.txt
    python scripts/convert_api_docs.py [api_full.txt]

If no argument is given the script looks for api_full.txt in the repo root.
Output goes to api_docs/ at the repo root.
"""

import re
import sys
from pathlib import Path



_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_TXT = _REPO_ROOT / "api_full.txt"
FULL_TEXT = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_TXT
OUT_DIR = _REPO_ROOT / "api_docs"

# pdftotext 1-based physical page = printed page + 18
# 0-based array index = printed page + 17
PAGE_OFFSET = 17

# ---------------------------------------------------------------------------
# Chapter manifest: (chapter_num_or_None, title, first_printed_page, part)
# None = Part divider (no file, just context for index)
# ---------------------------------------------------------------------------
CHAPTERS = [
    # Part I
    (1,  "Technical Overview",                   3,    "I: REST Calls"),
    (2,  "Calling SOLIDserver Services",          5,    "I: REST Calls"),
    (3,  "SOLIDserver Key Services",              8,    "I: REST Calls"),
    (4,  "Calling Services With TAGS",            12,   "I: REST Calls"),
    # Part II IPAM
    (5,  "Space",                                 24,   "II: IPAM"),
    (6,  "IPv4 Network",                          41,   "II: IPAM"),
    (7,  "IPv6 Network",                          82,   "II: IPAM"),
    (8,  "IPv4 Pool",                             118,  "II: IPAM"),
    (9,  "IPv6 Pool",                             141,  "II: IPAM"),
    (10, "IPv4 Address",                          163,  "II: IPAM"),
    (11, "IPv6 Address",                          206,  "II: IPAM"),
    (12, "IPv4 Address Alias",                    233,  "II: IPAM"),
    (13, "IPv6 Address Alias",                    242,  "II: IPAM"),
    # Part III DHCP
    (14, "DHCPv4 Server",                         255,  "III: DHCP"),
    (15, "DHCPv6 Server",                         272,  "III: DHCP"),
    (16, "DHCPv4 Shared Network",                 287,  "III: DHCP"),
    (17, "DHCPv6 Shared Network",                 298,  "III: DHCP"),
    (18, "DHCPv4 Scope",                          309,  "III: DHCP"),
    (19, "DHCPv6 Scope",                          339,  "III: DHCP"),
    (20, "DHCPv4 Group",                          362,  "III: DHCP"),
    (21, "DHCPv6 Group",                          376,  "III: DHCP"),
    (22, "DHCPv4 Range",                          380,  "III: DHCP"),
    (23, "DHCPv6 Range",                          401,  "III: DHCP"),
    (24, "DHCPv4 Lease",                          421,  "III: DHCP"),
    (25, "DHCPv6 Lease",                          446,  "III: DHCP"),
    (26, "DHCPv4 Static",                         460,  "III: DHCP"),
    (27, "DHCPv6 Static",                         487,  "III: DHCP"),
    (28, "DHCPv4 Option",                         507,  "III: DHCP"),
    (29, "DHCPv6 Option",                         513,  "III: DHCP"),
    (30, "DHCPv4 ACL and ACL Entry",              518,  "III: DHCP"),
    (31, "DHCPv6 ACL and ACL Entry",              540,  "III: DHCP"),
    (32, "DHCPv4 Failover Channel",               562,  "III: DHCP"),
    # Part IV DNS
    (33, "DNS Server",                            575,  "IV: DNS"),
    (34, "DNS View",                              597,  "IV: DNS"),
    (35, "DNS Zone",                              627,  "IV: DNS"),
    (36, "DNS Resource Record",                   673,  "IV: DNS"),
    (37, "DNS ACL",                               710,  "IV: DNS"),
    (38, "TSIG Key",                              720,  "IV: DNS"),
    (39, "DNSSEC",                                731,  "IV: DNS"),
    # Part V NOM
    (40, "Network Object Manager Folder",         744,  "V: NOM"),
    (41, "Network Object",                        757,  "V: NOM"),
    (42, "Interface",                             774,  "V: NOM"),
    # Part VI Application
    (43, "Application",                           796,  "VI: Application"),
    (44, "Application Pool",                      813,  "VI: Application"),
    (45, "Application Node",                      830,  "VI: Application"),
    # Part VII Guardian
    (46, "Guardian Policy",                       849,  "VII: Guardian"),
    # Part VIII Cloud Observer
    (47, "Cloud Observer Plugin",                 865,  "VIII: Cloud Observer"),
    (48, "Cloud Observer Worker",                 868,  "VIII: Cloud Observer"),
    (49, "Cloud Observer Folder",                 883,  "VIII: Cloud Observer"),
    (50, "Cloud Observer Instance",               891,  "VIII: Cloud Observer"),
    (51, "Cloud Observer Network",                907,  "VIII: Cloud Observer"),
    (52, "Cloud Observer IP Address",             923,  "VIII: Cloud Observer"),
    # Part IX NetChange
    (53, "Network Device",                        940,  "IX: NetChange"),
    (54, "IPv4 Route",                            965,  "IX: NetChange"),
    (55, "IPv6 Route",                            980,  "IX: NetChange"),
    (56, "NetChange VLAN",                        995,  "IX: NetChange"),
    (57, "Port",                                  1004, "IX: NetChange"),
    (58, "NetChange IPv4 Address",                1022, "IX: NetChange"),
    (59, "NetChange IPv6 Address",                1032, "IX: NetChange"),
    (60, "Discovered Item",                       1042, "IX: NetChange"),
    # Part X Workflow
    (61, "Workflow Request",                      1058, "X: Workflow"),
    # Part XI Device Manager
    (62, "Device Manager Device",                 1090, "XI: Device Manager"),
    (63, "Device Manager Port and Interface",     1107, "XI: Device Manager"),
    # Part XII VLAN Manager
    (64, "VLAN Domain",                           1136, "XII: VLAN Manager"),
    (65, "VLAN Range",                            1151, "XII: VLAN Manager"),
    (66, "VLAN",                                  1168, "XII: VLAN Manager"),
    # Part XIII VRF
    (67, "VRF",                                   1184, "XIII: VRF"),
    (68, "VRF Route Target",                      1195, "XIII: VRF"),
    # Part XIV Administration
    (69, "Services Management",                   1205, "XIV: Administration"),
    (70, "Group",                                 1212, "XIV: Administration"),
    (71, "User",                                  1226, "XIV: Administration"),
    (72, "Custom Data",                           1244, "XIV: Administration"),
    (73, "Network and Services Configuration",    1262, "XIV: Administration"),
]

# SDK models currently implemented (used to annotate the index)
SDK_CHAPTERS = {5, 6, 8, 10, 33, 34, 35, 36, 64, 65, 66, 67}

# Boilerplate text that appears identically in every *_list service.
# We replace it with a single compact note to reduce noise.
BOILERPLATE_PATTERNS = [
    # The full SELECT explanation
    (r"SELECT\n\s+A statement that allows you to specify which column\(s\).*?"
     r"(?=WHERE|\Z)", "SELECT", True),
    (r"WHERE\n\s+A clause that allows you to filter the result\..*?"
     r"(?=ORDERBY|\Z)", "WHERE", True),
    (r"ORDERBY\n\s+A clause that allows you to sort the result.*?"
     r"(?=offset|\Z)", "ORDERBY", True),
    (r"offset\n\s+The number of rows to skip.*?(?=limit|\Z)", "offset", True),
    (r"limit\n\s+The maximum number of results.*?(?=\n[A-Z]|\Z)", "limit", True),
]

# Footnote patterns to strip
FOOTNOTE_RE = re.compile(r"^\d+\s+It is no longer possible.*$", re.MULTILINE)


def clean_page(text: str) -> str:
    """Remove page headers and page number footers from a single pdftotext page."""
    lines = text.split("\n")
    cleaned = []
    skip_next = False

    first_nonempty = next((i for i, ln in enumerate(lines) if ln.strip()), -1)

    for i, line in enumerate(lines):
        stripped = line.strip()

        if skip_next:
            skip_next = False
            if "It is no longer possible" in line or stripped.startswith("It is"):
                continue

        # Lone single-digit line = footnote superscript; skip it + next line
        if re.fullmatch(r"\d", stripped):
            skip_next = True
            continue

        # Page number lines: a bare 3-4 digit number (any indentation)
        if re.fullmatch(r"\d{3,4}", stripped):
            continue

        # Chapter start-page title (e.g. "Chapter 33. DNS Server") — redundant with file header
        if re.match(r"^Chapter \d+\.", stripped):
            continue

        # Interior page header: first non-empty line, heavily indented chapter title
        if i == first_nonempty and line.startswith(" " * 15) and stripped:
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


def extract_chapter_text(pages: list[str], start_printed: int, end_printed: int) -> str:
    """Extract and clean the raw text for a printed-page range."""
    start_idx = start_printed + PAGE_OFFSET
    end_idx = end_printed + PAGE_OFFSET
    # Clamp to actual page count
    start_idx = max(0, min(start_idx, len(pages) - 1))
    end_idx = max(0, min(end_idx, len(pages) - 1))
    raw_pages = pages[start_idx : end_idx + 1]
    cleaned = [clean_page(p) for p in raw_pages]
    return "\n".join(cleaned)


def detect_services(text: str) -> list[str]:
    """Extract service names (function-style identifiers before ' — ')."""
    return re.findall(r"^\s+(\w+)\s+—\s+", text, re.MULTILINE)


def normalize_indentation(text: str) -> str:
    """Reduce excessive leading whitespace while keeping relative indentation."""
    lines = text.split("\n")
    result = []
    for line in lines:
        # Count leading spaces
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        # Collapse deep indentation: every 3 leading spaces → 1 level (3 is the
        # minimum description indent used in the PDF, so this preserves param vs desc)
        new_indent = min(indent // 3, 3)
        result.append("  " * new_indent + stripped)
    return "\n".join(result)


def collapse_blank_lines(text: str, max_consecutive: int = 2) -> str:
    """Collapse runs of more than max_consecutive blank lines."""
    return re.sub(rf"\n{{{max_consecutive + 1},}}", "\n" * max_consecutive, text)


def strip_footnotes(text: str) -> str:
    return FOOTNOTE_RE.sub("", text)


def format_as_markdown(chapter_num: int, title: str, part: str, raw_text: str) -> str:
    """Convert cleaned raw text to markdown."""
    # --- Detect services in this chapter ---
    services = detect_services(raw_text)

    # --- Normalize whitespace ---
    text = normalize_indentation(raw_text)
    text = strip_footnotes(text)
    text = collapse_blank_lines(text)

    lines = text.split("\n")
    out: list[str] = []

    # File header
    out.append(f"# Chapter {chapter_num}: {title}")
    out.append("")
    out.append(f"**Part {part}**  ")
    if services:
        out.append(f"**Services:** {', '.join(f'`{s}`' for s in services)}")
    out.append("")
    out.append("---")
    out.append("")

    # Process lines, upgrading section structure to markdown
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # "Name" section → service header
        if stripped == "Name" and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            # service_name — description
            m = re.match(r"^(\w+)\s+—\s+(.+)$", next_line)
            if m:
                svc, desc = m.group(1), m.group(2)
                out.append(f"## `{svc}`")
                out.append("")
                out.append(f"**{desc}**")
                out.append("")
                i += 2
                continue

        # "Description", "Input Parameters", "Output Parameters" → h3
        if stripped in ("Description", "Input Parameters", "Output Parameters",
                        "Mandatory Input Parameters"):
            out.append(f"### {stripped}")
            out.append("")
            i += 1
            continue

        # Collapse the standard list boilerplate (SELECT/WHERE/ORDERBY/offset/limit)
        # Detect start of boilerplate block
        if stripped in ("SELECT", "WHERE", "ORDERBY", "offset", "limit") and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ""
            is_boilerplate = (
                (stripped == "SELECT" and "allows you to specify which column" in next_stripped) or
                (stripped == "WHERE" and "allows you to filter the result" in next_stripped) or
                (stripped == "ORDERBY" and "allows you to sort the result" in next_stripped) or
                (stripped == "offset" and "rows to skip" in next_stripped) or
                (stripped == "limit" and "maximum number of results" in next_stripped)
            )
            if is_boilerplate:
                # Skip until we hit a non-indented line or another section
                i += 1
                while i < len(lines):
                    line = lines[i]
                    ls = line.strip()
                    # Stop at next parameter (non-indented non-empty line that doesn't start a sentence)
                    if ls and not line.startswith("  ") and ls != "":
                        # Next param or section — don't consume it
                        break
                    i += 1
                continue

        # Parameter names: a bare identifier (possibly with 1 indent level = 2 spaces),
        # followed by a more-indented description. Formats as **bold**.
        # Covers both top-level params (0 indent) and section-nested params (2 spaces).
        param_match = re.match(r"^[a-z_][a-z0-9_]*$", stripped)
        if param_match and stripped and not stripped.startswith("#"):
            # Check next non-empty line is more indented
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            next_line = lines[j] if j < len(lines) else ""
            current_indent = len(line) - len(line.lstrip())
            next_indent = len(next_line) - len(next_line.lstrip()) if next_line.strip() else 0
            if next_line.strip() and next_indent > current_indent:
                out.append((" " * current_indent) + f"**{stripped}**")
                i += 1
                continue

        # Default: emit as-is
        out.append(line)
        i += 1

    # Append list of standard params note after "Input Parameters" section when it existed
    final_text = "\n".join(out)

    # Insert the standard params note after "### Input Parameters" if SELECT/WHERE appear
    # (we stripped them above, so add a compact reference)
    if "### Input Parameters" in final_text:
        final_text = final_text.replace(
            "### Input Parameters\n",
            "### Input Parameters\n\n"
            "> **Standard list params** (for `*_list` services): `SELECT`, `WHERE`, `ORDERBY`, "
            "`offset`, `limit`, `NO_PARENT_CLASS_PARAM`, `TAGS`. See Chapter 3–4.\n\n",
            1,  # only first occurrence
        )

    return collapse_blank_lines(final_text)


def chapter_filename(num: int, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return f"ch{num:02d}_{slug}.md"


def build_index(chapters_meta: list[dict]) -> str:
    lines = [
        "# SOLIDserver REST API v8.4 — Reference Index",
        "",
        "Converted from `SOLIDserver_API-Reference_REST-8.4.pdf`.",
        "One file per chapter. `[SDK]` = model implemented in eip-pydantic.",
        "",
    ]
    current_part = None
    for m in chapters_meta:
        part = m["part"]
        if part != current_part:
            lines.append(f"## Part {part}")
            lines.append("")
            current_part = part
        sdk_tag = " `[SDK]`" if m["num"] in SDK_CHAPTERS else ""
        lines.append(f"- [{m['num']}. {m['title']}]({m['filename']}){sdk_tag}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Reading full text...", flush=True)
    full_text = FULL_TEXT.read_text(encoding="utf-8", errors="replace")

    # Split into pages on form-feed character
    pages = full_text.split("\x0c")
    print(f"Total pages: {len(pages)}", flush=True)

    chapters_meta = []
    for idx, (num, title, start_page, part) in enumerate(CHAPTERS):
        # Compute end page = next chapter's start - 1 (or last page)
        if idx + 1 < len(CHAPTERS):
            end_page = CHAPTERS[idx + 1][2] - 1
        else:
            end_page = len(pages) - PAGE_OFFSET - 1  # last printed page

        print(f"  ch{num:02d} {title} (pp {start_page}–{end_page})...", flush=True)

        raw = extract_chapter_text(pages, start_page, end_page)
        md = format_as_markdown(num, title, part, raw)

        fname = chapter_filename(num, title)
        (OUT_DIR / fname).write_text(md, encoding="utf-8")

        chapters_meta.append({"num": num, "title": title, "part": part, "filename": fname})

    # Write index
    index_md = build_index(chapters_meta)
    (OUT_DIR / "README.md").write_text(index_md, encoding="utf-8")
    print(f"\nDone. {len(CHAPTERS)} files + README.md written to {OUT_DIR}/", flush=True)


if __name__ == "__main__":
    main()
