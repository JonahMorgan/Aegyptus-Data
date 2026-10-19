"""Phonological plausibility of etymology links, using the learned sound correspondences.

1. Held-out evaluation: 5-fold cross-validation over ORAEC's linked pairs; each held-out true pair is
   ranked against the same younger word paired with random older-stage lemmas (AUC, and how often
   the true ancestor beats all 20 decoys).
2. Disagreements: for Coptic words where ORAEC and Wiktionary name different ancestors, a model
   trained without those words says which ancestor fits the sound correspondences better.
3. Every descends_from edge between two lemmas gets a score; the lowest are listed for review.

python Unified/analysis/etymology_scoring.py
  -> Unified/output/reports/etymology_scoring.{md,json}, link_scores.jsonl
"""
import json
import random
from collections import defaultdict

from common import REPORTS, ancestors, is_canonical, load_merged, md_table, parents, write_report
from correspondence import EditModel, linked_pairs, tokens
from compare import skeleton
from translit import egy_loose_key

MIN_TOKENS = 3  # shorter words (grammatical morphemes like ⲉ-, ⲁ) score low by construction; not flagged

STAGES = [("egy", "dem"), ("dem", "cop"), ("egy", "cop")]
FOLDS = 5
DECOYS = 20


def train(entries, id_pairs):
    pairs = [(tokens(entries[a]), tokens(entries[b])) for a, b in id_pairs]
    return EditModel().train([(s, t) for s, t in pairs if s and t])


def cross_validate(entries, id_pairs, pool, rng):
    """AUC of true-pair scores vs decoy scores, and top-1 rate among DECOYS+1 candidates, on held-out folds."""
    by_younger = defaultdict(list)
    for a, b in id_pairs:
        by_younger[b].append(a)
    youngers = sorted(by_younger)
    rng.shuffle(youngers)
    wins = ties = total = top1 = n = 0
    true_scores = []
    fold_model = {}  # younger id -> the model trained without it
    for k in range(FOLDS):
        test = set(youngers[k::FOLDS])
        model = train(entries, [(a, b) for a, b in id_pairs if b not in test])
        for b in test:
            fold_model[b] = model
            tb = tokens(entries[b])
            true = max(model.score(tokens(entries[a]), tb) for a in by_younger[b])
            decoys = [model.score(tokens(entries[d]), tb) for d in rng.sample(pool, DECOYS) if d not in by_younger[b]]
            true_scores.append(true)
            for d in decoys:
                wins += true > d
                ties += true == d
                total += 1
            top1 += all(true > d for d in decoys)
            n += 1
    return ({"held_out_words": n, "auc": round((wins + 0.5 * ties) / total, 3), "top1_of_21": round(top1 / n, 3)},
            sorted(true_scores), fold_model)


def stage_model_for(entries, older, younger):
    return (entries[older]["lang"], entries[younger]["lang"])


def main():
    rng = random.Random(0)
    entries, relations = load_merged()
    pairs_by_stage = linked_pairs(entries, relations)
    pools = {lang: [eid for eid, e in entries.items() if e["lang"] == lang and is_canonical(eid) and e.get("lemma")]
             for lang in ("egy", "dem")}

    # 1. held-out evaluation
    evaluation, thresholds, fold_models = {}, {}, {}
    for older, younger in STAGES:
        ev, scores, fold_models[(older, younger)] = cross_validate(entries, pairs_by_stage[(older, younger)], pools[older], rng)
        evaluation[f"{older}→{younger}"] = ev
        thresholds[(older, younger)] = scores[len(scores) // 20]  # 5th percentile of held-out true links
        print(f"{older}→{younger}: {ev}")

    # 2. ORAEC vs Wiktionary disagreements, judged by models that never saw those words
    up = parents(relations)
    disputed = []
    for eid in entries:
        if not eid.startswith("cop:C"):
            continue
        o, w = ancestors(up, eid, "oraec"), ancestors(up, eid, "wiktionary")
        o = {a for a in o if a in entries and entries[a].get("lemma")}
        w = {a for a in w if a in entries and entries[a].get("lemma")}
        ko = {egy_loose_key(entries[a]["lemma"]) for a in o}
        kw = {egy_loose_key(entries[a]["lemma"]) for a in w}
        if o and w and not (ko & kw) and not ({skeleton(k) for k in ko} & {skeleton(k) for k in kw}):
            disputed.append((eid, o, w))
    excluded = {d[0] for d in disputed}
    models = {st: train(entries, [(a, b) for a, b in pairs_by_stage[st] if b not in excluded]) for st in STAGES}

    def best(cop, cands):
        scored = [(models[(entries[a]["lang"], "cop")].score(tokens(entries[a]), tokens(entries[cop])), a) for a in cands
                  if entries[a]["lang"] in ("egy", "dem")]
        return max(scored) if scored else (None, None)

    verdicts = []
    for cop, o, w in disputed:
        so, ao = best(cop, o)
        sw, aw = best(cop, w)
        if so is None or sw is None:
            continue
        verdicts.append({"coptic": f"{cop} {entries[cop]['lemma']}",
                         "oraec": f"{entries[ao]['lemma']} ({ao})", "oraec_score": round(so, 3),
                         "wiktionary": f"{entries[aw]['lemma']} ({aw})", "wiktionary_score": round(sw, 3),
                         "favours": "oraec" if so > sw + 0.05 else "wiktionary" if sw > so + 0.05 else "tie"})
    fav = {k: sum(v["favours"] == k for v in verdicts) for k in ("oraec", "wiktionary", "tie")}

    # 3. score every inherited-line edge out of sample: edges the models were trained on (ORAEC) use the
    #    cross-validation model that held that word out; all other edges use the full model.
    full = {st: train(entries, pairs_by_stage[st]) for st in STAGES}
    scored = []
    for r in relations:
        if r["type"] != "descends_from" or r["src"] not in entries or r["dst"] not in entries:
            continue
        a, b = entries[r["dst"]], entries[r["src"]]
        st = (a["lang"], b["lang"])
        if st not in full or not a.get("lemma") or not b.get("lemma"):
            continue
        ta, tb = tokens(a), tokens(b)
        if not ta or not tb:
            continue
        model = fold_models[st].get(r["src"]) if "oraec" in r["sources"] else None
        s = (model or full[st]).score(ta, tb)
        short = min(len(ta), len(tb)) < MIN_TOKENS
        scored.append({"src": r["src"], "dst": r["dst"], "src_lemma": b["lemma"], "dst_lemma": a["lemma"],
                       "sources": r["sources"], "score": round(s, 3), "short": short,
                       "below_5pct": s < thresholds[st] and not short})
    with open(REPORTS / "link_scores.jsonl", "w", encoding="utf-8") as f:
        for x in sorted(scored, key=lambda x: x["score"]):
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    flagged = [x for x in scored if x["below_5pct"]]
    flagged_by_source = defaultdict(lambda: [0, 0])
    for x in scored:
        key = "+".join(sorted(x["sources"]))
        flagged_by_source[key][1] += 1
        flagged_by_source[key][0] += x["below_5pct"]

    data = {"evaluation": evaluation, "disagreements": {"count": len(verdicts), "favours": fav, "items": verdicts},
            "flagged_by_source": {k: {"flagged": a, "edges": b} for k, (a, b) in flagged_by_source.items()}}
    md = ["# Etymology scoring", "",
          "Scores come from the sound-correspondence models in `correspondences.md`: per-letter log-likelihood "
          "ratio of the best alignment against a model that only inserts and deletes. Higher = more regular.", "",
          "## Held-out evaluation", "",
          f"{FOLDS}-fold cross-validation on ORAEC links. Each held-out true link is compared with the same "
          f"younger word paired with {DECOYS} random lemmas of the older stage. Random decoys are easy to beat; "
          "the realistic test is `suggestions.md`, where candidates must also share meaning.", ""]
    md.append(md_table(["stage", "held-out words", "AUC", "true link ranked first of 21"],
                       [[k, v["held_out_words"], v["auc"], f"{v['top1_of_21']:.0%}"] for k, v in evaluation.items()]))
    md += ["", "## ORAEC vs Wiktionary disagreements", "",
           f"{len(verdicts)} Coptic words where the two name ancestors that differ even at the strong-consonant level "
           "(the 'disagree' column of comparison.md). "
           "Judged by models trained without these words (margin 0.05).", "",
           f"Phonology favours ORAEC in {fav['oraec']}, Wiktionary in {fav['wiktionary']}, tie in {fav['tie']}. "
           "This is phonological fit, not correctness: several Wiktionary 'wins' differ only by a feminine -t. "
           "Treat these as leads for review.", ""]
    md.append(md_table(["Coptic", "ORAEC", "score", "Wiktionary", "score", "favours"],
                       [[v["coptic"], v["oraec"], v["oraec_score"], v["wiktionary"], v["wiktionary_score"], v["favours"]]
                        for v in sorted(verdicts, key=lambda v: v["favours"])]))
    md += ["", "## Low-scoring links", "",
           "Edges scoring below the 5th percentile of held-out true links for their stage, by asserting source(s). "
           "All scores are out of sample (ORAEC edges are scored by the cross-validation model that never saw them). "
           f"Words under {MIN_TOKENS} letters on either side are not flagged (short morphemes score low regardless).", ""]
    md.append(md_table(["sources", "flagged", "edges", "rate"],
                       [[k, a, b, f"{a / b:.0%}"] for k, (a, b) in sorted(flagged_by_source.items(), key=lambda kv: -kv[1][1])]))
    md += ["", "Lowest 25 (full list in `link_scores.jsonl`):", ""]
    md.append(md_table(["younger", "older", "sources", "score"],
                       [[f"{x['src_lemma']} ({x['src']})", f"{x['dst_lemma']} ({x['dst']})", "+".join(x["sources"]), x["score"]]
                        for x in sorted(flagged, key=lambda x: x["score"])[:25]]))
    write_report("etymology_scoring", data, "\n".join(md) + "\n")


if __name__ == "__main__":
    main()
