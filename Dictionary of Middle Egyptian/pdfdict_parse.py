"""Parse Dickson's Dictionary of Middle Egyptian PDF into middle_egyptian_entries.json.

Entries look like:   [Hrt S] garden {D2 D21 X1 N1 N37 N21 Z1}
i.e. [MdC transliteration] English definition {Gardiner signs}, and may wrap across
lines and pages. The whole book is concatenated (minus running headers) and parsed in
one pass, so entries spanning a page break are kept and every entry gets the page it
starts on.

Usage: python pdfdict_parse.py [--pdf DictionaryOfMiddleEgyptian.pdf] [--out middle_egyptian_entries.json]
"""
import argparse
import bisect
import json
import re
from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).resolve().parent
FIRST_PAGE = 5  # 1-based; earlier pages are front matter
ENTRY = re.compile(r"\[([^\[\]{}]+)\]\s*([^\[\]{}]*?)\s*\{([^{}\[\]]*)\}", re.S)
SECTION = re.compile(r"^\s*([A-Z][a-z]?)\s+[–-]\s+(.+?)\s*$")


def page_text(page):
    """Page text without the running header ('Dictionary of Middle Egyptian', section title, page number)."""
    lines = page.get_text().split("\n")
    section = None
    body = []
    for i, line in enumerate(lines):
        if i < 4 and line.strip() == "Dictionary of Middle Egyptian":
            continue
        if i < 4 and SECTION.match(line):
            section = SECTION.match(line).group(1)
            continue
        if i < 4 and line.strip().isdigit():
            continue
        body.append(line)
    return " ".join(body), section


def parse(pdf_path):
    doc = fitz.open(pdf_path)
    chunks, starts, pages, sections = [], [], [], []
    offset = 0
    for pno in range(FIRST_PAGE - 1, len(doc)):
        text, section = page_text(doc[pno])
        starts.append(offset)
        pages.append(pno + 1)
        sections.append(section)
        chunks.append(text)
        offset += len(text) + 1
    full = " ".join(chunks)

    entries = []
    for m in ENTRY.finditer(full):
        translit, definition, gardiner = (re.sub(r"\s+", " ", g).strip() for g in m.groups())
        if not translit:
            continue
        i = bisect.bisect_right(starts, m.start()) - 1
        entry = {"transliteration": translit, "definition": definition, "gardiner": gardiner, "page": pages[i]}
        if sections[i]:
            entry["section"] = sections[i]
        entries.append(entry)
    return entries, len(doc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=HERE / "DictionaryOfMiddleEgyptian.pdf")
    ap.add_argument("--out", default=HERE / "middle_egyptian_entries.json")
    args = ap.parse_args()

    entries, n_pages = parse(args.pdf)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    covered = {e["page"] for e in entries}
    empty = [p for p in range(FIRST_PAGE, n_pages + 1) if p not in covered]
    print(f"{len(entries)} entries from pages {FIRST_PAGE}-{n_pages}; pages with no entry start: {empty}")


if __name__ == "__main__":
    main()
