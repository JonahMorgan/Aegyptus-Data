"""Sound correspondences between Egyptian, Demotic and Coptic, learned from ID-linked etymologies.

Model: stochastic edit distance (Ristad & Yianilos) trained by hard EM. Each etymology pair
(older form, younger form) is aligned with substitutions e->c, deletions e->∅ and insertions ∅->c;
op probabilities are re-estimated from the alignments until they stop changing. The first iteration
is seeded from letter co-occurrence within linked pairs (IBM Model 1 style), not from any assumed
phonetic values, so the tables are learned from the data alone.

python Unified/analysis/correspondence.py
  -> Unified/output/reports/correspondences.{md,json}   (egy→cop, egy→dem, dem→cop tables)
  -> Unified/output/reports/correspondence_model.json  (op probabilities, reused by etymology scoring)
"""
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict

from common import REPORTS, is_canonical, load_merged, md_table, parents, write_report
from translit import egy_key

# --- tokenizers -------------------------------------------------------------------------------

COPTIC_DIGRAPHS = ["ⲟⲩ", "ⲉⲓ"]
COPTIC_VOWELS = set("ⲁⲉⲏⲓⲟⲱⲩ") | {"ⲟⲩ", "ⲉⲓ"}


def coptic_tokens(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^Ⲁ-⳿Ϣ-ϯ]", "", s)
    out, i = [], 0
    while i < len(s):
        if s[i:i + 2] in COPTIC_DIGRAPHS:
            out.append(s[i:i + 2])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return out


def egy_tokens(s):
    return list(egy_key(s))


# --- model ------------------------------------------------------------------------------------

EPS = None  # empty side of an insertion/deletion


class EditModel:
    def __init__(self, smoothing=0.5):
        self.logp = {}
        self.smoothing = smoothing
        self.default = math.log(1e-6)

    def cost(self, e, c):
        return -self.logp.get((e, c), self.default)

    def align(self, src, tgt):
        """Viterbi alignment -> (total cost, [(e, c), ...])"""
        n, m = len(src), len(tgt)
        D = [[math.inf] * (m + 1) for _ in range(n + 1)]
        B = [[None] * (m + 1) for _ in range(n + 1)]
        D[0][0] = 0.0
        for i in range(n + 1):
            for j in range(m + 1):
                if i and D[i - 1][j] + self.cost(src[i - 1], EPS) < D[i][j]:
                    D[i][j], B[i][j] = D[i - 1][j] + self.cost(src[i - 1], EPS), (i - 1, j)
                if j and D[i][j - 1] + self.cost(EPS, tgt[j - 1]) < D[i][j]:
                    D[i][j], B[i][j] = D[i][j - 1] + self.cost(EPS, tgt[j - 1]), (i, j - 1)
                if i and j and D[i - 1][j - 1] + self.cost(src[i - 1], tgt[j - 1]) < D[i][j]:
                    D[i][j], B[i][j] = D[i - 1][j - 1] + self.cost(src[i - 1], tgt[j - 1]), (i - 1, j - 1)
        ops, i, j = [], n, m
        while (i, j) != (0, 0):
            pi, pj = B[i][j]
            ops.append((src[i - 1] if pi < i else EPS, tgt[j - 1] if pj < j else EPS))
            i, j = pi, pj
        return D[n][m], ops[::-1]

    def fit_counts(self, counts):
        alphabet_src = {e for e, _ in counts} | {EPS}
        alphabet_tgt = {c for _, c in counts} | {EPS}
        total = sum(counts.values()) + self.smoothing * len(alphabet_src) * len(alphabet_tgt)
        self.logp = {(e, c): math.log((counts.get((e, c), 0) + self.smoothing) / total)
                     for e in alphabet_src for c in alphabet_tgt if not (e is EPS and c is EPS)}
        self.default = math.log(self.smoothing / total)

    def train(self, pairs, iterations=25):
        # Initialize from co-occurrence (IBM-Model-1 style): every letter pair that appears in the same
        # etymology gets a share of a count. No hand-written phonetic prior is involved.
        counts = Counter()
        for src, tgt in pairs:
            for e in src:
                counts[(e, EPS)] += 0.5
                for c in tgt:
                    counts[(e, c)] += 1.0 / len(tgt)
            for c in tgt:
                counts[(EPS, c)] += 0.5
        self.fit_counts(counts)
        prev = None
        for it in range(iterations):
            counts = Counter()
            total = 0.0
            for src, tgt in pairs:
                cost, ops = self.align(src, tgt)
                total += cost
                counts.update(ops)
            self.fit_counts(counts)
            if prev is not None and abs(prev - total) < 1e-3 * abs(total):
                break
            prev = total
        self.counts = counts
        return self

    def score(self, src, tgt):
        """Per-token log-likelihood ratio of the best alignment vs. a model that only inserts and deletes."""
        cost, _ = self.align(src, tgt)
        null = sum(self.cost(e, EPS) for e in src) + sum(self.cost(EPS, c) for c in tgt)
        return (null - cost) / max(1, len(src) + len(tgt))

    def to_json(self):
        return {f"{e or '∅'}>{c or '∅'}": round(lp, 4) for (e, c), lp in self.logp.items()}

    @classmethod
    def from_json(cls, d):
        m = cls()
        for k, v in d.items():
            e, c = k.split(">", 1)
            m.logp[(None if e == "∅" else e, None if c == "∅" else c)] = v
        m.default = min(m.logp.values())
        return m


# --- training data ------------------------------------------------------------------------------

def linked_pairs(entries, relations, source="oraec"):
    """ID-linked (older, younger) lemma pairs from one source's descends_from edges, by stage."""
    up = parents(relations)
    out = defaultdict(list)
    for src_id, by in up.items():
        for dst_id in by.get(source, ()):
            a, b = entries.get(dst_id), entries.get(src_id)
            if not a or not b or not a.get("lemma") or not b.get("lemma"):
                continue
            out[(a["lang"], b["lang"])].append((dst_id, src_id))
            if a["lang"] == "dem":  # also pair the Coptic word with the Demotic word's Egyptian ancestor
                for anc in up.get(dst_id, {}).get(source, ()):
                    if anc in entries and entries[anc].get("lemma") and b["lang"] == "cop":
                        out[("egy", "cop")].append((anc, src_id))
    return {k: sorted(set(v)) for k, v in out.items()}


def tokens(entry):
    return coptic_tokens(entry["lemma"]) if entry["lang"] == "cop" else egy_tokens(entry["lemma"])


def train_stage(entries, id_pairs, exclude=()):
    pairs = [(tokens(entries[a]), tokens(entries[b])) for a, b in id_pairs if b not in exclude and a not in exclude]
    pairs = [(s, t) for s, t in pairs if s and t]
    return EditModel().train(pairs), pairs


# --- report -----------------------------------------------------------------------------------

def position(i, n):
    return "initial" if i == 0 else "final" if i == n - 1 else "medial"


def correspondence_table(model, entries, id_pairs):
    """For every older-stage letter: what it becomes, by position, with examples."""
    table = defaultdict(lambda: defaultdict(Counter))
    examples = defaultdict(lambda: defaultdict(list))
    for a, b in id_pairs:
        src, tgt = tokens(entries[a]), tokens(entries[b])
        if not src or not tgt:
            continue
        _, ops = model.align(src, tgt)
        i = 0
        merged = []  # attach insertions (mostly vowels) to the preceding source letter for readability
        for e, c in ops:
            if e is EPS:
                if merged:
                    merged[-1][1].append(c)
                continue
            merged.append((e, [c] if c is not EPS else [], i))
            i += 1
        for e, cs, k in merged:
            outcome = "".join(x for x in cs if x not in COPTIC_VOWELS) or ("∅" if not cs else "V")
            pos = position(k, len(src))
            table[e][pos][outcome] += 1
            table[e]["all"][outcome] += 1
            if len(examples[e][outcome]) < 3:
                examples[e][outcome].append(f"{entries[a]['lemma']} → {entries[b]['lemma']}")
    return table, examples


STAGES = [("egy", "dem"), ("dem", "cop"), ("egy", "cop")]


def main():
    entries, relations = load_merged()
    pairs_by_stage = linked_pairs(entries, relations)
    data, md = {}, ["# Sound correspondences", "",
                    "Learned by `Unified/analysis/correspondence.py` from ORAEC's ID-linked etymologies "
                    "(stochastic edit distance, hard EM). For each older-stage letter: what it corresponds to in the "
                    "younger stage, overall and by position in the word. `∅` = lost; `V` = only a vowel; "
                    "otherwise the consonant(s) it aligns with (vowels stripped). Letters are TLA/Unicode "
                    "transliteration after normalization (ꞽ/i̯ → j).", ""]
    models = {}
    for older, younger in STAGES:
        id_pairs = pairs_by_stage.get((older, younger), [])
        model, pairs = train_stage(entries, id_pairs)
        models[f"{older}>{younger}"] = model
        table, examples = correspondence_table(model, entries, id_pairs)
        stage = f"{older}→{younger}"
        data[stage] = {"pairs": len(pairs), "letters": {
            e: {pos: dict(c.most_common()) for pos, c in by.items()} for e, by in table.items()},
            "examples": {e: dict(v) for e, v in examples.items()}}
        md += [f"## {stage}", "", f"{len(pairs)} linked pairs.", ""]
        rows = []
        for e, by in sorted(table.items(), key=lambda kv: -sum(kv[1]["all"].values())):
            n = sum(by["all"].values())
            if n < 8:
                continue
            top = ", ".join(f"{o} {c / n:.0%}" for o, c in by["all"].most_common(4))
            fin = by.get("final", Counter())
            nf = sum(fin.values())
            final = ", ".join(f"{o} {c / nf:.0%}" for o, c in fin.most_common(2)) if nf >= 5 else ""
            ex = "; ".join(examples[e][by["all"].most_common(1)[0][0]][:2])
            rows.append([e, n, top, final, ex])
        md.append(md_table([older, "n", f"→ {younger} (overall)", "word-final", "examples (top outcome)"], rows))
        md.append("")
    write_report("correspondences", data, "\n".join(md) + "\n")
    with open(REPORTS / "correspondence_model.json", "w", encoding="utf-8") as f:
        json.dump({k: m.to_json() for k, m in models.items()}, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
