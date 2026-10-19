"""Shared store for the unified dictionary. See SCHEMA.md."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = Path(__file__).resolve().parent / "output"

RELATION_TYPES = {"descends_from", "borrowed_from", "variant_of", "derived_from", "cognate", "see_also"}
LIST_FIELDS = ("forms", "senses", "refs")


def load_json(path):
    """Load JSON, tolerating UTF-8 BOM and legacy UTF-16 files."""
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return json.loads(raw.decode("utf-16"))
    return json.loads(raw.decode("utf-8-sig"))


def iter_jsonl(path):
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _content_key(item):
    return tuple(sorted((k, str(v)) for k, v in item.items() if k != "source"))


class Store:
    def __init__(self):
        self.entries = {}
        self.relations = {}
        self.aliases = {}  # provisional id -> canonical id

    def resolve(self, eid):
        while eid in self.aliases:
            eid = self.aliases[eid]
        return eid

    def add_entry(self, eid, lang, lemma=None, source=None, **fields):
        """Create or merge an entry. List fields are appended (deduped); scalars fill gaps only."""
        eid = self.resolve(eid)
        e = self.entries.get(eid)
        if e is None:
            e = self.entries[eid] = {"id": eid, "lang": lang, "sources": {}}
        if lemma and not e.get("lemma"):
            e["lemma"] = lemma
        for k, v in fields.items():
            if v in (None, "", [], {}):
                continue
            if k in LIST_FIELDS:
                # Same content from a second source is not repeated; the first source keeps credit.
                lst = e.setdefault(k, [])
                seen = {_content_key(i) for i in lst}
                for item in v:
                    ck = _content_key(item)
                    if ck not in seen:
                        seen.add(ck)
                        lst.append(item)
            elif k == "sources":
                for name, ref in v.items():
                    e["sources"].setdefault(name, ref)
            elif k not in e:
                e[k] = v
        if source and source not in e["sources"]:
            e["sources"][source] = {}
        return e

    def add_relation(self, src, dst, rtype, source, note=None):
        """Record an edge. IDs are resolved through aliases at write time, so merges stay cheap."""
        assert rtype in RELATION_TYPES, rtype
        key = (src, dst, rtype)
        r = self.relations.get(key)
        if r is None:
            r = self.relations[key] = {"src": src, "dst": dst, "type": rtype, "sources": []}
        if source not in r["sources"]:
            r["sources"].append(source)
        if note and "note" not in r:
            r["note"] = note

    def resolved_relations(self):
        out = {}
        for r in self.relations.values():
            src, dst = self.resolve(r["src"]), self.resolve(r["dst"])
            if src == dst:
                continue
            key = (src, dst, r["type"])
            o = out.setdefault(key, {"src": src, "dst": dst, "type": r["type"], "sources": []})
            for s in r["sources"]:
                if s not in o["sources"]:
                    o["sources"].append(s)
            if r.get("note") and "note" not in o:
                o["note"] = r["note"]
        return out

    def merge(self, provisional, canonical):
        """Fold a provisional entry (e.g. egy:wikt:...) into a canonical one."""
        provisional, canonical = self.resolve(provisional), self.resolve(canonical)
        if provisional == canonical:
            return
        p = self.entries.pop(provisional, None)
        if p:
            fields = {k: v for k, v in p.items() if k not in ("id", "lang", "lemma")}
            self.add_entry(canonical, p["lang"], p.get("lemma"), **fields)
        self.aliases[provisional] = canonical

    def write(self, outdir=OUTPUT):
        outdir.mkdir(parents=True, exist_ok=True)
        with open(outdir / "entries.jsonl", "w", encoding="utf-8") as f:
            for e in sorted(self.entries.values(), key=lambda e: e["id"]):
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        with open(outdir / "relations.jsonl", "w", encoding="utf-8") as f:
            for r in sorted(self.resolved_relations().values(), key=lambda r: (r["src"], r["dst"], r["type"])):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
