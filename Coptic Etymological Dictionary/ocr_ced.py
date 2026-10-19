"""OCR Černý's Coptic Etymological Dictionary and align entries to BBAW lemma IDs via their Crum refs.

Requires Tesseract (English data is enough to find the "(Crum 13b)" anchors) and `pip install pytesseract`.
Pass --langs eng+cop+grc once Coptic/Greek models are installed to also read the headwords.
Each CED entry prints "(Crum 13b)"; the text from one such anchor to the next is assigned to the
BBAW lemmas that ced_page_index.json lists for that page with the same Crum ref.

Usage: python ocr_ced.py [--pages 11 41] [--all] [--langs eng]   ->  ced_entries.jsonl (+ ocr_cache/ page texts)
"""
import argparse
import json
import re
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

HERE = Path(__file__).resolve().parent
PDF = HERE / "Černý J. - Coptic Etymological Dictionary.scan.pdf"
CACHE = HERE / "ocr_cache"
CRUM = re.compile(r"\(\s*Crum\s+(\d+)\s*([ab])?", re.I)


def ocr_page(pdf_page, doc, langs, dpi=400):
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"{pdf_page:04d}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    pix = doc[pdf_page - 1].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    text = pytesseract.image_to_string(img, lang=langs, config="--psm 4")
    cached.write_text(text, encoding="utf-8")
    return text


def split_entries(text):
    """[(crum_ref, entry_text)] split at lines containing a (Crum ...) anchor."""
    lines = text.split("\n")
    starts = [(i, m.group(1) + (m.group(2) or "")) for i, l in enumerate(lines) for m in [CRUM.search(l)] if m]
    out = []
    for k, (i, ref) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        out.append((ref, "\n".join(lines[i:end]).strip()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="*", type=int, default=[11, 41], help="printed CED pages")
    ap.add_argument("--all", action="store_true", help="every page in ced_page_index.json")
    ap.add_argument("--langs", default="eng", help="Tesseract languages, e.g. eng+cop+grc")
    args = ap.parse_args()

    index = json.loads((HERE / "ced_page_index.json").read_text(encoding="utf-8"))
    pages = sorted(int(p) for p in index) if args.all else args.pages
    doc = fitz.open(PDF)
    aligned = unaligned = 0
    with open(HERE / "ced_entries.jsonl", "w", encoding="utf-8") as out:
        for p in pages:
            info = index.get(str(p), {"pdf_page": p + 20, "entries": []})
            for ref, text in split_entries(ocr_page(info["pdf_page"], doc, args.langs)):
                ids = [e["id"] for e in info["entries"] if ref in e["crum"] or ref.rstrip("ab") in e["crum"]]
                aligned += bool(ids)
                unaligned += not ids
                out.write(json.dumps({"ced_page": p, "crum": ref, "ids": ids, "text": text}, ensure_ascii=False) + "\n")
    print(f"{aligned} entries aligned to BBAW ids, {unaligned} unaligned, over {len(pages)} pages")


if __name__ == "__main__":
    main()
