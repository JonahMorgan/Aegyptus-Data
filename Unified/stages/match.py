"""Resolve provisional entries ({lang}:{source}:{word}) onto canonical TLA/BBAW entries.

For each provisional entry, candidates are canonical entries of the same language with the
same normalized key (falling back to the loose key). Ties are broken, in order, by:
  1. TLA IDs the source itself cites (Wiktionary {{R:egy:TLA}})
  2. English gloss overlap (also rejects a match whose glosses share no words)
  3. part of speech (also rejects an explicit conflict)
  4. shared etymological neighbours (e.g. both already linked to the same Coptic word)
Proper names (capitalized) only match proper names.
Only an unambiguous result is merged; otherwise the candidates are recorded on the entry.
Provisional entries left unmatched are merged with each other when they share a key.
"""
import re
from collections import Counter, defaultdict

from translit import coptic_key, egy_loose_key

POS_NORMAL = {
    "subst.": "noun", "noun": "noun", "proper noun": "noun", "name": "noun",
    "verb": "verb", "verbum": "verb",
    "adj.": "adjective", "adjective": "adjective", "adverb": "adverb", "adv.": "adverb",
    "präp.": "preposition", "preposition": "preposition", "pronoun": "pronoun", "pron.": "pronoun",
    "particle": "particle", "partikel": "particle", "numeral": "numeral", "zahlwort": "numeral",
}
SOURCE_ORDER = ["wikt", "cdo", "dme"]


def _pos(e):
    p = (e.get("pos") or "").lower().strip()
    return POS_NORMAL.get(p) or POS_NORMAL.get(p.split()[0] if p else "", None)


_STOP = set("""a an the of to in on for and or by with from as at be is are was been being it its
this that one who which some any into out up off over under (of) etc thing person something someone""".split())


def _proper(e):
    lemma = (e.get("lemma") or "").lstrip("(.-=⸗")
    return bool(lemma) and lemma[0].isupper()


def _gloss_words(e):
    words = set()
    for s in e.get("senses") or []:
        if s.get("lang") not in (None, "en"):
            continue
        for w in re.findall(r"[a-z]{3,}", s["gloss"].lower()):
            if w not in _STOP:
                words.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return words


def _overlap(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def _provisional(eid):
    return eid.count(":") > 1


def _loose(e):
    return egy_loose_key(e.get("lemma")) if e["lang"] != "cop" else e.get("key")


def run(store):
    stats = Counter()
    index, loose = defaultdict(list), defaultdict(list)
    for e in store.entries.values():
        if _provisional(e["id"]) or e["lang"] not in ("egy", "dem", "cop") or not e.get("key"):
            continue
        index[(e["lang"], e["key"])].append(e["id"])
        loose[(e["lang"], _loose(e))].append(e["id"])
        if e["lang"] == "cop":
            for f in e.get("forms") or []:
                k = coptic_key(f.get("form"))
                if k and e["id"] not in loose[("cop", k)]:
                    loose[("cop", k)].append(e["id"])

    neighbours = defaultdict(set)
    for r in store.relations.values():
        neighbours[r["src"]].add(r["dst"])
        neighbours[r["dst"]].add(r["src"])

    merged_into = defaultdict(list)  # canonical id -> ids folded into it
    for alias in store.aliases:
        merged_into[store.resolve(alias)].append(alias)

    def nbrs(eid):
        return {store.resolve(n) for i in [eid, *merged_into.get(eid, ())] for n in neighbours.get(i, ())}

    provisional = [e for e in store.entries.values() if _provisional(e["id"]) and e["lang"] in ("egy", "dem", "cop")]
    # Coptic first (English glosses on both sides make it the most reliable), then Demotic, then Egyptian,
    # so the neighbour tie-break for older stages can see already-resolved Coptic descendants.
    lang_order = {"cop": 0, "dem": 1, "egy": 2}
    provisional.sort(key=lambda e: (lang_order[e["lang"]],
                                    SOURCE_ORDER.index(e["id"].split(":")[1]) if e["id"].split(":")[1] in SOURCE_ORDER else 9))

    for e in provisional:
        eid = e["id"]
        if store.resolve(eid) != eid or not e.get("key"):
            continue
        lang, key = e["lang"], e["key"]
        exact = [store.resolve(c) for c in index.get((lang, key), [])]
        near = [store.resolve(c) for c in loose.get((lang, _loose(e)), [])]
        cands = list(dict.fromkeys(exact or near))
        method = "key"
        # proper names are capitalized in TLA/Wiktionary; never cross a name with a common word
        if not eid.startswith("egy:dme:"):
            cands = [c for c in cands if _proper(store.entries[c]) == _proper(e)]
        else:
            cands = [c for c in cands if not _proper(store.entries[c])]
        if not cands:
            stats[f"{lang}_no_candidate"] += 1
            continue

        mine = _gloss_words(e)
        if mine:
            # glosses decide between homographs, and can pull in a form-level (near) match the key missed
            pool = list(dict.fromkeys(cands + near)) if lang == "cop" else cands
            scored = sorted(((_overlap(mine, _gloss_words(store.entries[c])), c) for c in pool), reverse=True)
            glossed = [(sc, c) for sc, c in scored if _gloss_words(store.entries[c])]
            if glossed and glossed[0][0] > 0 and (len(glossed) == 1 or glossed[0][0] > glossed[1][0]):
                cands, method = [glossed[0][1]], "gloss"
            elif glossed and all(sc == 0 for sc, _ in glossed):
                cands = [c for c in cands if not _gloss_words(store.entries[c])]
                if not cands:
                    store.entries[eid]["candidates"] = [c for _, c in glossed][:8]
                    stats[f"{lang}_rejected_gloss_mismatch"] += 1
                    continue

        if len(cands) > 1:
            cited = [f"{lang}:{i}" for i in e["sources"].get("wiktionary", {}).get("tla_ids", [])]
            hit = [c for c in cands if c in cited]
            if len(hit) == 1:
                cands, method = hit, "tla_ref"
        if _pos(e):
            same = [c for c in cands if _pos(store.entries[c]) in (None, _pos(e))]
            if not same:
                store.entries[eid]["candidates"] = cands[:8]
                stats[f"{lang}_rejected_pos_conflict"] += 1
                continue
            if len(cands) > 1:
                exact_pos = [c for c in same if _pos(store.entries[c]) == _pos(e)]
                if len(exact_pos) == 1:
                    cands, method = exact_pos, "pos"
                else:
                    cands = same
        if len(cands) > 1:
            mine_n = nbrs(eid)
            shared = [c for c in cands if mine_n & nbrs(c)]
            if len(shared) == 1:
                cands, method = shared, "neighbour"
        if len(cands) == 1:
            for ref in e["sources"].values():
                ref["match"] = method
            store.merge(eid, cands[0])
            merged_into[cands[0]].append(eid)
            stats[f"{lang}_merged_by_{method}"] += 1
        else:
            store.entries[eid]["candidates"] = cands[:8]
            stats[f"{lang}_ambiguous"] += 1

    # leftover provisional entries from different sources describing the same word:
    # merge only across sources, and only when their English glosses don't contradict each other
    groups = defaultdict(list)
    for e in list(store.entries.values()):
        if _provisional(e["id"]) and e.get("key") and "candidates" not in e:
            groups[(e["lang"], e["key"])].append(e["id"])
    for ids in groups.values():
        if len(ids) < 2:
            continue
        ids.sort(key=lambda i: SOURCE_ORDER.index(i.split(":")[1]) if i.split(":")[1] in SOURCE_ORDER else 9)
        heads = []  # one surviving entry per distinct sense
        for i in ids:
            gi = _gloss_words(store.entries[i])
            target = None
            for h in heads:
                if h.split(":")[1] == i.split(":")[1]:
                    continue  # never fold two entries of the same source together
                gh = _gloss_words(store.entries[h])
                if not gi or not gh or _overlap(gi, gh) > 0:
                    target = h
                    break
            if target:
                store.merge(i, target)
                stats["provisional_merged_together"] += 1
            else:
                heads.append(i)
    return dict(stats)
