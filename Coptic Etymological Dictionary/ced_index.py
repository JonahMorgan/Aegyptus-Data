"""Page index for Černý's Coptic Etymological Dictionary (CED), built from the unified dictionary.

BBAW cites CED pages ("CED 12") and Crum pages ("CD 13b") for each Coptic lemma. Every CED entry
prints its Crum reference "(Crum 13b)", so OCR output can be aligned to BBAW lemma IDs by Crum ref
without having to read the Coptic headword correctly.

Output: ced_page_index.json = {printed CED page: {"pdf_page": n, "entries": [{id, lemma, crum}]}}
Run Unified/build.py first.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENTRIES = HERE.parent / "Unified" / "output" / "entries.jsonl"
PDF_OFFSET = 20  # printed page 11 is PDF page 31
LAST_PAGE = 384  # last printed page; BBAW has a few out-of-range CED refs (489, 540, 832)


def crum_refs(loc):
    """'2a' / '13a-b' / '844a, 845b' -> ['2a', '13a', '13b', '844a', '845b']"""
    out = []
    for part in re.split(r"[;,]\s*", loc or ""):
        m = re.match(r"(\d+)([ab])?(?:\s*-\s*([ab]))?", part.strip())
        if m:
            page, a, b = m.groups()
            out += [page + a] + ([page + b] if b else []) if a else [page]
    return out


def ced_pages(loc):
    pages = []
    for part in re.split(r"[;,]\s*", loc or ""):
        m = re.match(r"(\d+)(?:\s*[-–]\s*(\d+))?", part.strip())
        if m:
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
            pages += list(range(a, b + 1))
    return pages


def build():
    index = defaultdict(lambda: {"entries": []})
    for line in open(ENTRIES, encoding="utf-8"):
        e = json.loads(line)
        if not e["id"].startswith("cop:C"):
            continue
        refs = e.get("refs") or []
        crum = [c for r in refs if r["work"] == "CD" for c in crum_refs(r.get("loc"))]
        for r in refs:
            if r["work"] == "CED":
                for p in ced_pages(r.get("loc")):
                    if p > LAST_PAGE:
                        continue
                    index[p]["pdf_page"] = p + PDF_OFFSET
                    index[p]["entries"].append({"id": e["id"], "lemma": e.get("lemma"), "crum": list(dict.fromkeys(crum))})
    return dict(sorted(index.items()))


if __name__ == "__main__":
    idx = build()
    with open(HERE / "ced_page_index.json", "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    n = sum(len(v["entries"]) for v in idx.values())
    print(f"{n} lemma references over {len(idx)} CED pages ({min(idx)}-{max(idx)})")
