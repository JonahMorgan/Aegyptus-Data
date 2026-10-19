"""Loading helpers shared by the analysis scripts."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.stdout.reconfigure(encoding="utf-8")

from schema import OUTPUT  # noqa: E402

REPORTS = OUTPUT / "reports"
INHERITED = ("egy", "dem", "cop")
STOP = set("""a an the of to in on for and or by with from as at be is are was been being it its this that one who
which some any into out up off over under etc thing person something someone (of) kind sort type""".split())


def load_merged():
    entries = {}
    with open(OUTPUT / "entries.jsonl", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            entries[e["id"]] = e
    with open(OUTPUT / "relations.jsonl", encoding="utf-8") as f:
        relations = [json.loads(line) for line in f]
    return entries, relations


def is_canonical(eid):
    return eid.count(":") == 1


def gloss_words(e, source=None, lang="en"):
    words = set()
    for s in e.get("senses") or []:
        if s.get("lang") not in (None, lang) or (source and s.get("source") != source):
            continue
        for w in re.findall(r"[a-z]{3,}", s["gloss"].lower()):
            if w not in STOP:
                words.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return words


def parents(relations, rtype="descends_from"):
    """src -> source -> set(dst)"""
    up = defaultdict(lambda: defaultdict(set))
    for r in relations:
        if r["type"] == rtype:
            for s in r["sources"]:
                up[r["src"]][s].add(r["dst"])
    return up


def ancestors(up, eid, source=None):
    """All descends_from ancestors of eid, optionally following only one source's edges."""
    out, stack = set(), [eid]
    while stack:
        x = stack.pop()
        for s, dsts in up.get(x, {}).items():
            if source and s != source:
                continue
            for y in dsts:
                if y not in out:
                    out.add(y)
                    stack.append(y)
    return out


def write_report(name, data, markdown):
    REPORTS.mkdir(parents=True, exist_ok=True)
    with open(REPORTS / f"{name}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    (REPORTS / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(f"wrote {REPORTS / name}.md / .json")


def md_table(headers, rows):
    out = ["| " + " | ".join(map(str, headers)) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(map(str, r)) + " |" for r in rows]
    return "\n".join(out)
