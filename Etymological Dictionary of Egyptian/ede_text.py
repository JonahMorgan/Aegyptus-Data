"""Unicode text extraction for EDE vol. 3, undoing the PDF's custom font encodings (see ede_glyph_map.json)."""
import json
import string
from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).resolve().parent
_MAP = json.loads((HERE / "ede_glyph_map.json").read_text(encoding="utf-8"))
GLYPHS = _MAP["map"]
ENCODED_FONTS = set(_MAP["ENCODED_FONTS"])
LIGATURES = {"fi", "fl"}
_PASS = set(string.digits + string.punctuation + " ")


def remap_char(font, c):
    m = GLYPHS.get(font, {}).get(c)
    if m is not None:
        return m
    if font in ENCODED_FONTS:
        return c if c in _PASS else "�"
    if not c.isprintable():
        return "�"
    return c


def page_lines(page, min_size=0.0):
    """Yield lines as lists of (text, font, size, bbox) runs with remapped text.

    Spans are joined without inserting spaces (spacing lives in the characters). A ligature glyph
    is followed by a spurious space in this PDF ('suf\\x03 x'), which is dropped.
    """
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            runs = []
            drop_space = False
            for span in line["spans"]:
                if span["size"] < min_size:
                    continue
                out = []
                for ch in span["chars"]:
                    c = remap_char(span["font"], ch["c"])
                    if drop_space and c == " ":
                        drop_space = False
                        continue
                    drop_space = c in LIGATURES
                    out.append(c)
                if out:
                    runs.append(("".join(out), span["font"], round(span["size"], 1), tuple(line["bbox"])))
            if runs:
                yield runs


def page_text(page):
    return "\n".join("".join(r[0] for r in runs) for runs in page_lines(page))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    doc = fitz.open(HERE / "Etymological-Dictionary-of-Egyptian-vol3.pdf")
    for p in sys.argv[1:] or ["41"]:
        print(f"===== page {p}")
        for runs in page_lines(doc[int(p) - 1]):
            print(" ⟂ ".join(f"{t}[{f.replace('Baskerville', 'B')}:{s}]" for t, f, s, _ in runs))
