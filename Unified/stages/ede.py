"""Etymological Dictionary of Egyptian (Takács) vol. 3, from Etymological Dictionary of Egyptian/ede_lemmas.json.

Headwords like 'mtr.t > mt( j).t ~ mtj ~ mtr.w' become one entry (first form) with the rest as forms.
The Afroasiatic comparanda stay in the source file (copyrighted); the entry carries the page ref.
"""
import re
from collections import Counter

from schema import ROOT, load_json
from translit import egy_key

EDE_JSON = ROOT / "Etymological Dictionary of Egyptian" / "ede_lemmas.json"
SPLIT = re.compile(r"\s*(?:~|>|<|/|–)\s*")


def run(store):
    stats = Counter()
    seen = Counter()  # EDE prints homographs as separate entries; keep them apart
    if not EDE_JSON.exists():
        return {"skipped": "run Etymological Dictionary of Egyptian/parse_ede.py first"}
    for x in load_json(EDE_JSON):
        forms = [f.strip("()* ") for f in SPLIT.split(x["headword_translit"]) if f.strip("()* ")]
        if not forms or not egy_key(forms[0]):
            stats["skipped_no_headword"] += 1
            continue
        lemma = forms[0]
        seen[lemma] += 1
        eid = f"egy:ede:{lemma}" + (f"#{seen[lemma]}" if seen[lemma] > 1 else "")
        senses = []
        if x.get("gloss"):
            senses.append({"lang": "de", "gloss": x["gloss"], "source": "ede"})
        if x.get("gloss_en"):
            senses.append({"lang": "en", "gloss": x["gloss_en"], "source": "ede"})
        store.add_entry(eid, "egy", lemma, source="ede", key=egy_key(lemma),
                        forms=[{"form": f, "source": "ede"} for f in forms[1:]],
                        senses=senses,
                        refs=[{"work": "EDE III", "loc": str(x["page"]), "source": "ede"}],
                        sources={"ede": {"headword": x["headword"], "page": x["page"]}})
        stats["entries"] += 1
    return dict(stats)
