"""Cross-source comparison of the unified dictionary.

python Unified/analysis/compare.py  ->  Unified/output/reports/comparison.{md,json}

Sections: coverage per language, how much of each ID-less source got attached to a TLA/BBAW entry,
English-gloss agreement where two sources describe the same lemma, and agreement on the
Egyptian/Demotic ancestors of Coptic words (ORAEC vs Coptic Dictionary Online vs Wiktionary).
"""
from collections import Counter
from itertools import combinations

from common import (INHERITED, ancestors, gloss_words, is_canonical, load_merged, md_table, parents,
                    write_report)
from translit import egy_loose_key

WEAK = set("ꜣjwyꜥaeiou")


def skeleton(key):
    """Strong consonants only: sources often differ in writing weak radicals (ꜣ j w y ꜥ) and Demotic vowels."""
    return "".join(c for c in key if c not in WEAK)


GLOSS_SOURCES = ["bbaw", "wiktionary", "dme", "ede"]
LINK_SOURCES = ["oraec", "cdo", "wiktionary"]


def coverage(entries):
    out = {}
    for lang in INHERITED:
        canon = [e for e in entries.values() if e["lang"] == lang and is_canonical(e["id"])]
        prov = [e for e in entries.values() if e["lang"] == lang and not is_canonical(e["id"])]
        per_source = Counter(s for e in canon for s in e["sources"])
        multi = sum(1 for e in canon if len(set(e["sources"]) - {"oraec"}) >= 2)
        out[lang] = {"canonical": len(canon), "provisional": len(prov), "per_source": dict(per_source.most_common()),
                     "with_2plus_sources": multi,
                     "provisional_by_source": dict(Counter(e["id"].split(":")[1] for e in prov).most_common())}
    return out


def attach_rates(entries):
    """For sources without TLA/BBAW IDs: how many of their entries ended up on a canonical entry."""
    out = {}
    for src in ("wiktionary", "dme", "ede"):
        on_canon = sum(1 for e in entries.values() if is_canonical(e["id"]) and src in e["sources"])
        left = sum(1 for e in entries.values() if not is_canonical(e["id"]) and e["id"].split(":")[1] in (src, "wikt" if src == "wiktionary" else src)
                   and e["lang"] in INHERITED)
        ambiguous = sum(1 for e in entries.values() if not is_canonical(e["id"]) and "candidates" in e
                        and e["id"].split(":")[1] in (src, "wikt" if src == "wiktionary" else src))
        out[src] = {"attached": on_canon, "unattached": left, "of_which_ambiguous": ambiguous,
                    "rate": round(on_canon / max(1, on_canon + left), 3)}
    return out


def gloss_agreement(entries):
    out = {}
    for a, b in combinations(GLOSS_SOURCES, 2):
        c = Counter()
        for e in entries.values():
            if not is_canonical(e["id"]):
                continue
            ga, gb = gloss_words(e, a), gloss_words(e, b)
            if ga and gb:
                c["both"] += 1
                c["overlap"] += bool(ga & gb)
        if c["both"]:
            out[f"{a}~{b}"] = {"lemmas_glossed_by_both": c["both"], "share_with_word_overlap": round(c["overlap"] / c["both"], 3)}
    return out


def _cdo_keys(e):
    ety = e["sources"].get("cdo", {}).get("etymology") or {}
    return {egy_loose_key(v) for v in ety.values() if v}


def etymology_agreement(entries, relations):
    """Do two sources name the same ancestor (compared by normalized transliteration) for a Coptic word?"""
    up = parents(relations)
    per_word = {}
    for eid, e in entries.items():
        if not eid.startswith("cop:C"):
            continue
        keys = {}
        for src in ("oraec", "wiktionary"):
            anc = ancestors(up, eid, src)
            if anc:
                keys[src] = {egy_loose_key(entries[a].get("lemma")) for a in anc if a in entries and entries[a].get("lemma")}
        if _cdo_keys(e):
            keys["cdo"] = _cdo_keys(e)
        if keys:
            per_word[eid] = keys

    pairs = {}
    examples = {}
    for a, b in combinations(LINK_SOURCES, 2):
        c = Counter()
        ex = []
        for eid, keys in per_word.items():
            if a in keys and b in keys:
                if keys[a] & keys[b]:
                    c["agree"] += 1
                elif {skeleton(k) for k in keys[a]} & {skeleton(k) for k in keys[b]}:
                    c["same_skeleton"] += 1
                else:
                    c["disagree"] += 1
                    if len(ex) < 12:
                        ex.append({"coptic": f"{eid} {entries[eid].get('lemma')}", a: sorted(keys[a]), b: sorted(keys[b])})
            elif a in keys:
                c[f"only_{a}"] += 1
            elif b in keys:
                c[f"only_{b}"] += 1
        both = c["agree"] + c["same_skeleton"] + c["disagree"]
        c["agree_rate"] = round(c["agree"] / both, 3) if both else None
        c["agree_or_variant_rate"] = round((c["agree"] + c["same_skeleton"]) / both, 3) if both else None
        pairs[f"{a}~{b}"] = dict(c)
        examples[f"{a}~{b}"] = ex
    n_sources = Counter(len(k) for k in per_word.values())
    copt = sum(1 for eid in entries if eid.startswith("cop:C"))
    borrowed = {r["src"] for r in relations if r["type"] == "borrowed_from" and r["src"].startswith("cop:C")}
    no_ety = sum(1 for eid in entries if eid.startswith("cop:C") and eid not in per_word and eid not in borrowed)
    return {"coptic_lemmas": copt, "with_native_etymology_by_n_sources": dict(sorted(n_sources.items())),
            "with_greek_or_other_loan_source": len(borrowed), "with_no_etymology": no_ety,
            "pairs": pairs}, examples


def main():
    entries, relations = load_merged()
    cov = coverage(entries)
    att = attach_rates(entries)
    gl = gloss_agreement(entries)
    ety, examples = etymology_agreement(entries, relations)
    data = {"coverage": cov, "attach_rates": att, "gloss_agreement": gl, "etymology_agreement": ety,
            "etymology_disagreement_examples": examples}

    md = ["# Cross-source comparison", "",
          "Generated by `Unified/analysis/compare.py` from `Unified/output/`.", "", "## Coverage", ""]
    md.append(md_table(["language", "canonical entries", "with ≥2 sources", "still provisional"],
                       [[l, v["canonical"], v["with_2plus_sources"], v["provisional"]] for l, v in cov.items()]))
    md += ["", "Entries per source (canonical only):", ""]
    md.append(md_table(["language", "sources"], [[l, ", ".join(f"{s} {n}" for s, n in v["per_source"].items())] for l, v in cov.items()]))
    md += ["", "## Attaching ID-less sources", "",
           "Share of each source's Egyptian/Demotic/Coptic entries that the matcher attached to a TLA or BBAW entry.", ""]
    md.append(md_table(["source", "attached", "unattached", "ambiguous", "rate"],
                       [[s, v["attached"], v["unattached"], v["of_which_ambiguous"], v["rate"]] for s, v in att.items()]))
    md += ["", "## English gloss agreement", "",
           "For lemmas glossed in English by both sources: share where the glosses share at least one content word.",
           "Not independent evidence: the matcher itself rejects merges whose glosses share no words, so these rates are high by construction.", ""]
    md.append(md_table(["sources", "lemmas", "overlap"], [[k, v["lemmas_glossed_by_both"], v["share_with_word_overlap"]] for k, v in gl.items()]))
    md += ["", "## Etymologies of Coptic words", "",
           f"{ety['coptic_lemmas']} Coptic lemmas: {ety['with_greek_or_other_loan_source']} have a loan source, "
           f"{ety['with_no_etymology']} have no etymology from any source. Native etymologies by number of sources: "
           + ", ".join(f"{k} source(s): {v}" for k, v in ety["with_native_etymology_by_n_sources"].items()) + ".", "",
           "Pairwise agreement on the Egyptian/Demotic ancestor: do the two sources name any ancestor with the same",
           "loosely normalized transliteration (ꞽ/i̯/j, ḳ/q, y/j, z/s folded; dots, hyphens, suffix markers dropped)?",
           "\"Same skeleton\" = no exact match, but the same strong consonants once weak radicals (ꜣ j w y ꜥ) and",
           "Demotic vowels are dropped, i.e. a spelling variant of the same etymon rather than a different one.",
           "ORAEC and Coptic Dictionary Online are not independent: both derive from TLA's Coptic–Demotic–Egyptian links.", ""]
    md.append(md_table(["sources", "agree", "same skeleton", "disagree", "agree rate", "agree + skeleton", "only first", "only second"],
                       [[k, v.get("agree", 0), v.get("same_skeleton", 0), v.get("disagree", 0), v.get("agree_rate"), v.get("agree_or_variant_rate"),
                         v.get(f"only_{k.split('~')[0]}", 0), v.get(f"only_{k.split('~')[1]}", 0)] for k, v in ety["pairs"].items()]))
    md += ["", "### Disagreement samples", ""]
    for k, ex in examples.items():
        a, b = k.split("~")
        md.append(f"**{k}**")
        md.append("")
        md.append(md_table(["Coptic", a, b], [[x["coptic"], ", ".join(x[a]), ", ".join(x[b])] for x in ex[:8]]))
        md.append("")
    write_report("comparison", data, "\n".join(md) + "\n")


if __name__ == "__main__":
    main()
