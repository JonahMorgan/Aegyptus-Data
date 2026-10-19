"""TLA corpus: lemma inventory + attestation stats (token count, date range, corpus split) per TLA lemma ID."""
from collections import Counter, defaultdict

from schema import ROOT, iter_jsonl
from translit import egy_key

CORPORA = {
    "early-egyptian": ROOT / "TLA Corpus" / "early-egyptian" / "train.jsonl",
    "late-egyptian": ROOT / "TLA Corpus" / "late-egyptian" / "train.jsonl",
    "demotic": ROOT / "TLA Corpus" / "demotic" / "train.jsonl",
}
UPOS_TO_POS = {"NOUN": "noun", "PROPN": "proper noun", "VERB": "verb", "ADJ": "adjective", "ADV": "adverb",
               "ADP": "preposition", "PRON": "pronoun", "NUM": "numeral", "PART": "particle", "CCONJ": "conjunction",
               "SCONJ": "conjunction", "INTJ": "interjection", "DET": "determiner"}


def _tokens(lemmatization):
    """'d2779|mtw d1172|=w' -> [('d2779', 'mtw'), ('d1172', '=w')]; lemmas containing spaces are re-joined."""
    out = []
    for part in lemmatization.split(" "):
        if "|" in part:
            lid, lemma = part.split("|", 1)
            out.append([lid, lemma])
        elif out:
            out[-1][1] += " " + part
    return [tuple(t) for t in out]


def _int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def run(store):
    acc = defaultdict(lambda: {"tokens": 0, "lemma": Counter(), "upos": Counter(), "corpora": Counter(),
                               "date_min": None, "date_max": None})
    sentences = Counter()
    for corpus, path in CORPORA.items():
        for row in iter_jsonl(path):
            sentences[corpus] += 1
            toks = _tokens(row.get("lemmatization") or "")
            upos = (row.get("UPOS") or "").split(" ")
            dmin, dmax = _int(row.get("dateNotBefore")), _int(row.get("dateNotAfter"))
            for i, (lid, lemma) in enumerate(toks):
                if not lid or lid in ("0", "?"):
                    continue
                a = acc[lid]
                a["tokens"] += 1
                a["lemma"][lemma] += 1
                a["corpora"][corpus] += 1
                if len(upos) == len(toks):
                    a["upos"][upos[i]] += 1
                if dmin is not None:
                    a["date_min"] = dmin if a["date_min"] is None else min(a["date_min"], dmin)
                if dmax is not None:
                    a["date_max"] = dmax if a["date_max"] is None else max(a["date_max"], dmax)

    by_lang = Counter()
    for lid, a in acc.items():
        if lid.startswith("d") and lid[1:].isdigit():
            eid, lang = f"dem:{lid}", "dem"
        elif lid.isdigit():
            eid, lang = f"egy:{lid}", "egy"
        else:
            continue
        lemma = a["lemma"].most_common(1)[0][0]
        att = {"tokens": a["tokens"], "corpora": dict(a["corpora"]), "source": "tla"}
        if a["date_min"] is not None:
            att["date_min"], att["date_max"] = a["date_min"], a["date_max"]
        upos = a["upos"].most_common(1)[0][0] if a["upos"] else None
        store.add_entry(eid, lang, lemma, source="tla", key=egy_key(lemma),
                        pos=UPOS_TO_POS.get(upos), attestation=att, sources={"tla": {"id": lid}})
        by_lang[lang] += 1

    # entries that came from ORAEC before TLA ran still need a key
    for e in store.entries.values():
        if e["lang"] in ("egy", "dem") and "key" not in e and e.get("lemma"):
            e["key"] = egy_key(e["lemma"])
    return {"sentences": dict(sentences), "lemmas_attested": dict(by_lang)}
