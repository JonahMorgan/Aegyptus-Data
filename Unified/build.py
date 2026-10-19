"""Build the unified dictionary: python Unified/build.py  ->  Unified/output/{entries,relations}.jsonl"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from schema import OUTPUT, Store
from stages import coptic, dme, ede, match, tla, wiktionary

# Pipeline order: sources with stable IDs first, then ID-less sources, then the matcher.
PRIVATE_SOURCES = {"ede", "ced"}

STAGES = [
    ("coptic", coptic.run),
    ("tla", tla.run),
    ("wiktionary", wiktionary.run),
    ("dme", dme.run),
    ("ede", ede.run),
    ("match", match.run),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="run only these stages")
    ap.add_argument("--public", action="store_true",
                    help="drop glosses/forms from copyrighted sources (see SCHEMA.md) and write to output/public/")
    args = ap.parse_args()

    store = Store()
    report = {}
    for name, run in STAGES:
        if args.only and name not in args.only:
            continue
        print(f"[{name}]")
        stats = run(store)
        report[name] = stats
        for k, v in stats.items():
            print(f"  {k}: {v}")

    if args.public:
        for e in store.entries.values():
            for field in ("senses", "forms"):
                if field in e:
                    e[field] = [i for i in e[field] if i.get("source") not in PRIVATE_SOURCES]
                    if not e[field]:
                        del e[field]
        store.write(OUTPUT / "public")
    else:
        store.write()
    rels = store.resolved_relations().values()
    report["totals"] = {
        "entries": len(store.entries),
        "entries_by_lang": dict(Counter(e["lang"] for e in store.entries.values())),
        "provisional_entries": sum(1 for e in store.entries if e.count(":") > 1),
        "relations_by_type": dict(Counter(r["type"] for r in rels)),
    }
    with open((OUTPUT / "public" if args.public else OUTPUT) / "build_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
