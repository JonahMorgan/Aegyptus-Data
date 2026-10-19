"""Dictionary of Middle Egyptian (Dickson): MdC transliteration + English definition + Gardiner signs."""
import re
from collections import Counter

from schema import ROOT, load_json
from translit import egy_key, mdc_to_unicode

DME_JSON = ROOT / "Dictionary of Middle Egyptian" / "middle_egyptian_entries.json"


DME_POS = {"v": "verb", "n": "noun", "adj": "adjective", "adv": "adverb", "prep": "preposition",
           "prn": "pronoun", "particle": "particle", "interj": "interjection", "num": "numeral"}


def _pos(definition):
    m = re.match(r"\(([a-z]+)\.?", definition or "")
    return DME_POS.get(m.group(1)) if m else None


def _is_garbage(translit):
    return any(c in translit for c in "\n[]{}") or len(translit) > 25


def run(store):
    stats = Counter()
    seen = set()
    for x in load_json(DME_JSON):
        mdc = (x.get("transliteration") or "").strip()
        if not mdc or _is_garbage(mdc):
            stats["skipped_garbage"] += 1
            continue
        sig = (mdc, x.get("definition"), x.get("gardiner"), x.get("page"))
        if sig in seen:
            stats["skipped_duplicate"] += 1
            continue
        seen.add(sig)
        uni = mdc_to_unicode(mdc)
        eid = f"egy:dme:{uni}"
        gardiner = " ".join((x.get("gardiner") or "").split())
        forms = [{"form": uni, "gardiner": gardiner, "source": "dme"}] if gardiner else []
        store.add_entry(eid, "egy", uni, source="dme", key=egy_key(uni), pos=_pos(x.get("definition")),
                        senses=[{"lang": "en", "gloss": x["definition"], "source": "dme"}] if x.get("definition") else [],
                        forms=forms,
                        refs=[{"work": "DME", "loc": str(x.get("page")), "source": "dme"}],
                        sources={"dme": {"mdc": mdc}})
        stats["records"] += 1
    stats["entries"] = sum(1 for e in store.entries if e.startswith("egy:dme:"))
    return dict(stats)
