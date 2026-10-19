"""Per-source dictionaries in the unified schema, before any cross-source matching.

python Unified/export_sources.py  ->  Unified/output/sources/<source>/{entries,relations}.jsonl + summary.json
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from schema import OUTPUT, Store
from stages import coptic, dme, ede, tla, wiktionary

SOURCES = {
    "bbaw": lambda s: coptic.load_bbaw(s)[0],
    # CDO's etymologies name Demotic/Egyptian words by transliteration only; emit them as relations to provisional ids
    "cdo": lambda s: {**coptic.load_cdo(s, {}), **coptic.link_cdo_without_ids(s)},
    "oraec": coptic.load_oraec,
    "tla": tla.run,
    "wiktionary": wiktionary.run,
    "dme": dme.run,
    "ede": ede.run,
}


def summarize(store):
    entries = store.entries.values()
    rels = store.resolved_relations().values()
    return {
        "entries": len(store.entries),
        "by_lang": dict(Counter(e["lang"] for e in entries)),
        "with_en_gloss": sum(any(s.get("lang") == "en" for s in e.get("senses", [])) for e in entries),
        "with_forms": sum(bool(e.get("forms")) for e in entries),
        "with_attestation": sum("attestation" in e for e in entries),
        "relations": dict(Counter(r["type"] for r in rels)),
    }


def main():
    summary = {}
    for name, load in SOURCES.items():
        store = Store()
        load(store)
        store.write(OUTPUT / "sources" / name)
        summary[name] = summarize(store)
        print(f"{name:11s} {summary[name]['entries']:6d} entries  {summary[name]['relations']}")
    with open(OUTPUT / "sources" / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
