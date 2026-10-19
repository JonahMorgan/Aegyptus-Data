"""Candidate etymologies for Coptic lemmas that no source etymologizes.

Candidates: Egyptian/Demotic lemmas whose English glosses share a (not too common) content word with the
Coptic lemma's glosses. Ranking: phonological score from the learned correspondences (egy→cop or dem→cop),
plus a small bonus for gloss overlap. Suggestions are written to a report, never into the dictionary.

Validation first: Coptic words with a known ORAEC etymology are hidden (and excluded from training), and
we check whether the suggester recovers their ancestor. That tells you how far to trust the new suggestions.

python Unified/analysis/suggest.py  ->  Unified/output/reports/suggestions.{md,json}
"""
import math
import random
from collections import Counter, defaultdict

from common import ancestors, gloss_words, is_canonical, load_merged, md_table, parents, write_report
from correspondence import EditModel, linked_pairs, tokens
from translit import coptic_key

MAX_DF = 150        # ignore gloss words shared by more candidates than this ("god", "go", ...)
MAX_CANDIDATES = 120
GLOSS_WEIGHT = 1.0  # score = phonology + GLOSS_WEIGHT * jaccard(glosses)
TOP_K = 3


class Suggester:
    def __init__(self, entries, models):
        self.entries, self.models = entries, models
        self.index = defaultdict(set)
        self.words = {}
        for eid, e in entries.items():
            if e["lang"] in ("egy", "dem") and e.get("lemma") and tokens(e):
                w = gloss_words(e)
                if w:
                    self.words[eid] = w
                    for x in w:
                        self.index[x].add(eid)

    def candidates(self, cop):
        gw = gloss_words(self.entries[cop])
        hits = Counter()
        for x in gw:
            ids = self.index.get(x, ())
            if 0 < len(ids) <= MAX_DF:
                for i in ids:
                    hits[i] += 1
        return [i for i, _ in hits.most_common(MAX_CANDIDATES)], gw

    def suggest(self, cop, exclude=()):
        cands, gw = self.candidates(cop)
        tc = tokens(self.entries[cop])
        scored = []
        for c in cands:
            if c in exclude:
                continue
            e = self.entries[c]
            phon = self.models[e["lang"]].score(tokens(e), tc)
            gl = len(gw & self.words[c]) / len(gw | self.words[c])
            scored.append((phon + GLOSS_WEIGHT * gl, phon, gl, c))
        return sorted(scored, reverse=True)[:TOP_K]


def train_models(entries, pairs_by_stage, exclude):
    out = {}
    for older in ("egy", "dem"):
        pairs = [(tokens(entries[a]), tokens(entries[b])) for a, b in pairs_by_stage[(older, "cop")] if b not in exclude]
        out[older] = EditModel().train([(s, t) for s, t in pairs if s and t])
    return out


def keyset(entries, ids):
    from translit import egy_loose_key
    return {egy_loose_key(entries[i]["lemma"]) for i in ids if i in entries and entries[i].get("lemma")}


def first_en(e):
    return next((s["gloss"] for s in e.get("senses", []) if s.get("lang") == "en"), "")


def evaluate(sug, entries, words, truth_of):
    """Top-1/top-3 recovery of known ancestors; returns stats and (top-1 score, correct) pairs."""
    hit1 = hit3 = reachable = 0
    scored = []
    for cop in words:
        truth = keyset(entries, truth_of(cop))
        cands, _ = sug.candidates(cop)
        if not truth & keyset(entries, cands):
            continue  # true ancestor shares no English gloss word: a gloss-filter miss, not a ranking miss
        reachable += 1
        ranked = sug.suggest(cop)
        tops = [keyset(entries, [c]) for _, _, _, c in ranked]
        ok = bool(tops and tops[0] & truth)
        hit1 += ok
        hit3 += any(t & truth for t in tops)
        if ranked:
            scored.append((ranked[0][0], ok))
    return {"words": len(words), "ancestor_among_gloss_candidates": reachable,
            "top1_given_candidate": round(hit1 / max(1, reachable), 3),
            "top3_given_candidate": round(hit3 / max(1, reachable), 3),
            "top1_overall": round(hit1 / max(1, len(words)), 3)}, scored


def confidence_tiers(scored):
    """Score cut-offs at the terciles of held-out top-1 scores, with the precision observed in each."""
    scored = sorted(scored)
    cuts = [scored[len(scored) // 3][0], scored[2 * len(scored) // 3][0]]
    tiers = []
    for name, lo, hi in (("high", cuts[1], math.inf), ("medium", cuts[0], cuts[1]), ("low", -math.inf, cuts[0])):
        bucket = [ok for sc, ok in scored if lo <= sc < hi]
        tiers.append({"tier": name, "min_score": None if lo == -math.inf else round(lo, 3),
                      "top1_precision": round(sum(bucket) / max(1, len(bucket)), 3), "n": len(bucket)})
    return tiers


def main():
    rng = random.Random(1)
    entries, relations = load_merged()
    up = parents(relations)
    pairs_by_stage = linked_pairs(entries, relations)

    # --- validation on hidden known etymologies (ORAEC; models retrained without them) ------------
    known = [eid for eid in entries if eid.startswith("cop:C") and gloss_words(entries[eid])
             and ancestors(up, eid, "oraec")]
    rng.shuffle(known)
    held = set(known[:400])
    sug = Suggester(entries, train_models(entries, pairs_by_stage, held))
    validation, held_scores = evaluate(sug, entries, held, lambda c: ancestors(up, c, "oraec"))
    tiers = confidence_tiers(held_scores)
    print("validation:", validation)
    print("tiers:", tiers)

    # --- suggestions -------------------------------------------------------------------------------
    sug = Suggester(entries, train_models(entries, pairs_by_stage, set()))
    explained = {r["src"] for r in relations if r["type"] in ("descends_from", "borrowed_from", "derived_from")}
    targets = [eid for eid, e in entries.items() if eid.startswith("cop:C") and eid not in explained
               and gloss_words(e) and len(tokens(e)) >= 3]

    # Some targets do have an etymology elsewhere: on a Wiktionary page the matcher could not attach, or on a
    # duplicate BBAW lemma with the same spelling. Those are not gaps; the Wiktionary ones also give an
    # independent check, since Wiktionary links are not used to train the correspondence models.
    ety_by_key = defaultdict(lambda: defaultdict(set))
    for r in relations:
        if r["type"] == "descends_from" and r["src"].startswith("cop:") and r["src"] in entries:
            kind = "bbaw_duplicate" if r["src"].startswith("cop:C") else "wiktionary_unattached"
            ety_by_key[coptic_key(entries[r["src"]]["lemma"])][kind] |= ancestors(up, r["src"])
    elsewhere = {c: dict(ety_by_key[coptic_key(entries[c]["lemma"])]) for c in targets
                 if coptic_key(entries[c]["lemma"]) in ety_by_key}

    independent, _ = evaluate(sug, entries, [c for c in targets if elsewhere.get(c, {}).get("wiktionary_unattached")],
                              lambda c: elsewhere[c]["wiktionary_unattached"])
    print("independent (Wiktionary):", independent)

    results = []
    for cop in targets:
        top = sug.suggest(cop)
        if not top:
            continue
        r = {"coptic": cop, "lemma": entries[cop]["lemma"], "gloss": first_en(entries[cop]),
             "tier": next(t["tier"] for t in tiers if t["min_score"] is None or top[0][0] >= t["min_score"]),
             "suggestions": [{"id": c, "lemma": entries[c]["lemma"], "lang": entries[c]["lang"], "gloss": first_en(entries[c]),
                              "score": round(t, 3), "phonology": round(p, 3), "gloss_overlap": round(g, 3)}
                             for t, p, g, c in top]}
        if cop in elsewhere:
            r["etymology_elsewhere"] = sorted(elsewhere[cop])
        results.append(r)
    results.sort(key=lambda r: -r["suggestions"][0]["score"])
    gaps = [r for r in results if "etymology_elsewhere" not in r]
    data = {"validation": validation, "independent_validation": independent, "tiers": tiers,
            "targets": len(targets), "with_suggestions": len(results), "real_gaps": len(gaps),
            "tier_counts_real_gaps": dict(Counter(r["tier"] for r in gaps)), "suggestions": results}

    md = ["# Etymology suggestions for unetymologized Coptic lemmas", "",
          "Generated by `Unified/analysis/suggest.py`. Candidates must share an English gloss word with the Coptic "
          "lemma; they are ranked by the learned sound correspondences (`correspondences.md`) plus gloss overlap. "
          "These are leads for review, not etymologies.", "", "## How far to trust them", "",
          f"**Held-out ORAEC words.** {validation['words']} Coptic words with a known ORAEC etymology were hidden and the "
          f"models retrained without them. For {validation['ancestor_among_gloss_candidates']} the true ancestor passed the "
          f"gloss filter; among those the first suggestion was right {validation['top1_given_candidate']:.0%} of the time, "
          f"top {TOP_K} {validation['top3_given_candidate']:.0%}. Including gloss-filter misses, top-1 recovery is "
          f"{validation['top1_overall']:.0%}: most misses are Egyptian lemmas with no English gloss in the data.", "",
          f"**Independent check (Wiktionary).** {independent['words']} target words have an etymology on a Wiktionary page "
          f"the matcher could not attach to BBAW; Wiktionary links are not used for training. Where that ancestor passed the "
          f"gloss filter ({independent['ancestor_among_gloss_candidates']}), the first suggestion matched it "
          f"{independent['top1_given_candidate']:.0%} of the time, top {TOP_K} {independent['top3_given_candidate']:.0%}.", "",
          "**Confidence tiers** (top-1 precision on the held-out ORAEC words, by score):", "",
          md_table(["tier", "score ≥", "top-1 precision", "held-out words"],
                   [[t["tier"], t["min_score"] if t["min_score"] is not None else "—", f"{t['top1_precision']:.0%}", t["n"]]
                    for t in tiers]), "",
          f"## Suggestions", "",
          f"{len(targets)} Coptic lemmas have no attached etymology, an English gloss and ≥3 letters; {len(results)} got "
          f"suggestions. {len(results) - len(gaps)} of those do have an etymology elsewhere in the data (an unattached "
          f"Wiktionary page or a duplicate BBAW lemma with the same spelling; marked `etymology_elsewhere` in "
          f"`suggestions.json`), leaving {len(gaps)} real gaps: "
          + ", ".join(f"{n} {t}" for t, n in Counter(r["tier"] for r in gaps).most_common()) + " confidence.", "",
          "Strongest 60 real gaps (full list in `suggestions.json`):", ""]
    md.append(md_table(["Coptic", "gloss", "best candidate", "its gloss", "score (phon + gloss)", "tier", "runner-up"],
                       [[f"{r['lemma']} ({r['coptic']})", r["gloss"][:40],
                         f"{r['suggestions'][0]['lemma']} ({r['suggestions'][0]['id']})", r["suggestions"][0]["gloss"][:40],
                         f"{r['suggestions'][0]['score']} ({r['suggestions'][0]['phonology']} + {r['suggestions'][0]['gloss_overlap']})",
                         r["tier"], r["suggestions"][1]["lemma"] if len(r["suggestions"]) > 1 else ""] for r in gaps[:60]]))
    write_report("suggestions", data, "\n".join(md) + "\n")


if __name__ == "__main__":
    main()
