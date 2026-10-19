"""Parse the Etymological Dictionary of Egyptian (Takács), vol. 3 (m-), into ede_lemmas.json.

Layout (see ede_text.py for the font remapping that makes the text readable):
  - an entry starts with a bold 11pt headword at the hanging-indent margin, e.g.
        m “wer, was?” (OK, Wb II 4, 3–13) = “who, what?” (FD 100). Cp. ...
  - the body (Egyptian data, AA comparanda separated by | / || / |||) is 11pt
  - notes are 9pt paragraphs introduced by a small-caps label: ap:, dp:, lit.:, nb1: ...
  - y < 62 is the running head / page number
Takács writes aleph as "3" and ayin as "ʕ"; `headword_translit` converts them to ꜣ / ꜥ.

Usage: python parse_ede.py [--start-page 35] [--end-page 920] [--output ede_lemmas.json]
"""
import argparse
import json
import re
from pathlib import Path

import fitz  # PyMuPDF

from ede_text import page_lines

HERE = Path(__file__).resolve().parent
PDF = HERE / "Etymological-Dictionary-of-Egyptian-vol3.pdf"
HEADER_Y = 62
NOTE_LABEL = re.compile(r"^([a-z]{1,4}\d?\.?)\s*:\s*")
QUOTED = re.compile(r"“([^”]+)”")
QUOTED_EN = re.compile(r"=\s*“([^”]+)”")
SENSE_NUMBER = re.compile(r"^\(?\d+[a-z]?\)?\.?$")


def headword_translit(hw):
    s = hw.replace("3", "ꜣ").replace("ʕ", "ꜥ").replace("ʔ", "ꜣ")
    return re.sub(r"\s+", " ", s).strip()


def _join(lines):
    """Join wrapped lines; undo end-of-line hyphenation only inside ordinary Latin words."""
    out = ""
    for line in lines:
        line = line.rstrip()
        if out.endswith("-") and re.search(r"[a-z]{3}-$", out) and re.match(r"[a-z]", line):
            out = out[:-1] + line
        else:
            out = (out + " " + line) if out else line
    return re.sub(r"[ \t]+", " ", out).strip()


def iter_lines(doc, start, end):
    """(page, x0, size, first_font, runs, text, margin) for every line below the running head, in page order."""
    for pno in range(start - 1, min(end, len(doc))):
        lines = [runs for runs in page_lines(doc[pno]) if runs[0][3][1] >= HEADER_Y]
        if not lines:
            continue
        # classify by the line's largest run: body lines can start with a small phonetic glyph (8pt ʕ)
        size_of = lambda runs: max(r[2] for r in runs)
        body = [r for r in lines if size_of(r) >= 10.5]
        margin = min(r[0][3][0] for r in body) if body else None
        for runs in lines:
            text = "".join(r[0] for r in runs)
            if text.strip():
                yield pno + 1, runs[0][3][0], size_of(runs), runs[0][1], runs, text, margin


def parse(start, end):
    doc = fitz.open(PDF)
    entries, cur, body, notes, note = [], None, [], [], None

    def close():
        nonlocal cur, body, notes, note
        if cur is None:
            return
        if note:
            notes.append(note)
        cur["text"] = _join(body)
        cur["notes"] = [{"label": n["label"], "text": _join(n["lines"])} for n in notes]
        head_line = cur.pop("_head_line")
        m = QUOTED.search(head_line)
        if m:
            cur["gloss"] = m.group(1).strip()
        m = QUOTED_EN.search(head_line)
        if m:
            cur["gloss_en"] = m.group(1).strip()
        entries.append(cur)
        cur, body, notes, note = None, [], [], None

    for page, x0, size, font, runs, text, margin in iter_lines(doc, start, end):
        is_head = (size >= 10.5 and "Bold" in font and margin is not None and x0 <= margin + 1.5)
        hw = ""
        if is_head:
            for t, f, s, _ in runs:
                if "Bold" not in f:
                    break
                hw += t
            is_head = not SENSE_NUMBER.match(hw.strip())  # bold "(2)" / "1." sense numbers continue the entry
        if is_head:
            close()
            cur = {"headword": hw.strip(), "headword_translit": headword_translit(hw), "page": page, "_head_line": text}
            body = [text]
            continue
        if cur is None:
            continue
        if size < 10.5:
            label = NOTE_LABEL.match(text.strip()) if "SmallCap" in font else None
            if label:
                if note:
                    notes.append(note)
                note = {"label": label.group(1).rstrip("."), "lines": [text.strip()[label.end():]]}
            elif note:
                note["lines"].append(text)
            else:
                note = {"label": "", "lines": [text]}
        else:
            if note:
                notes.append(note)
                note = None
            body.append(text)
    close()
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-page", type=int, default=35, help="1-based; the dictionary proper starts on p. 35")
    ap.add_argument("--end-page", type=int, default=920, help="1-based, inclusive; 'quoted literature' starts on p. 921")
    ap.add_argument("--output", default=str(HERE / "ede_lemmas.json"))
    args = ap.parse_args()

    entries = parse(args.start_page, args.end_page)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    bad = sum(("�" in e["text"]) for e in entries)
    print(f"{len(entries)} entries, pages {args.start_page}-{args.end_page}; "
          f"{sum('gloss' in e for e in entries)} with a gloss ({sum('gloss_en' in e for e in entries)} English); {bad} contain an unmapped glyph (U+FFFD)")


if __name__ == "__main__":
    main()
