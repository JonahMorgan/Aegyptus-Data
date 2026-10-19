"""Wiktionary: Egyptian, Demotic and Coptic pages parsed by Wiktionary/parse_with_mwparserfromhell.py.

Everything enters under provisional IDs ({lang}:wikt:<word>); entries carrying an
{{R:egy:TLA|word|ID}} reference are folded into their TLA entry here, the rest are
resolved by stages/match.py.
"""
import re

from schema import ROOT, load_json
from translit import coptic_key, egy_key

WIKT = ROOT / "Wiktionary"
TLA_REF = re.compile(r"\{\{R:egy:TLA\|([^}]*)\}\}")
ETYM_TEMPLATE = re.compile(r"\{\{(inh\+?|der\+?|bor\+?|uder|lbor)\|(cop|egx-dem|egy)\|([a-z-]+)\|([^|}]*)")
SECTION = re.compile(r"^===+\s*Etymology[^=]*===+\s*$(.*?)(?=^===+\s*(?!Etymology)[^=]+===+\s*$|\Z)", re.M | re.S)


def wikt_lang(code):
    """Wiktionary language code -> (unified lang, dialect)."""
    if code == "egx-dem":
        return "dem", None
    if code.startswith("cop"):
        return "cop", code[4:] or None
    if code.startswith("egy"):
        return "egy", None
    return code, None


def node_id(lang, word):
    return f"{lang}:wikt:{word}"


def key_for(lang, word):
    return coptic_key(word) if lang == "cop" else egy_key(word) if lang in ("egy", "dem") else word


# template name -> index of the word among its |-separated parts ({{l|lang|word}}, {{t2i-Egyd|word|signs}})
_PLACEHOLDERS = {"egyptianterm", "term", "word"}
_WORD_PARAM = {"l": 2, "m": 2, "lang": 2, "t2i-Egyd": 1, "t2i": 1}


def clean_word(word, lang=None):
    """Unwrap wikitext left in a word: {{l|egx-dem|pr-ꜥꜣ}} -> pr-ꜥꜣ, {{t2i-Egyd|ꜥwy|Z1-2}} -> ꜥwy.
    Hieroglyph-only markup and Coptic-coded words without Coptic letters are dropped."""
    word = (word or "").strip()
    if "<hiero>" in word or "[[" in word or word.lower() in _PLACEHOLDERS:
        return None
    word = re.sub(r"^Reconstruction:[^/]+/", "*", word)  # reconstructed forms keep a leading *
    if word.startswith("{{") and word.endswith("}}"):
        parts = word[2:-2].split("|")
        idx = _WORD_PARAM.get(parts[0])
        if idx is None or len(parts) <= idx or "=" in parts[idx]:
            return None
        word = parts[idx].strip()
    if "{{" in word or "}}" in word:
        return None
    if lang == "cop" and not re.search(r"[Ⲁ-⳿Ϣ-ϯ]", word):
        return None
    return word or None


def _desc_word(node):
    """Descendant word, falling back to alt/alt1.. when the positional word is missing or corrupted (e.g. '665')."""
    word = (node.get("word") or "").strip()
    if word and not word.isdigit():
        return word
    params = node.get("params") or {}
    for k in ("alt", "alt1", "alt2", "tr"):
        if params.get(k):
            return params[k].strip()
    return None


def _tla_ids(wikitext):
    ids = []
    for m in TLA_REF.finditer(wikitext or ""):
        for part in m.group(1).split("|"):
            part = part.strip()
            if re.fullmatch(r"d?\d+", part) and part not in ids:
                ids.append(part)
    return ids


INHERITING = {"egy", "dem", "cop"}


def _edge_type(child_lang, parent_lang, borrowed):
    """descends_from only along the egy -> dem -> cop line; anything crossing into another language is a loan."""
    if borrowed or child_lang not in INHERITING or parent_lang not in INHERITING:
        return "borrowed_from"
    return "descends_from"


def _add_descendants(store, parent_id, nodes, stats, parent_lang="egy"):
    for node in nodes or []:
        lang, dialect = wikt_lang(node.get("language") or "")
        word = clean_word(_desc_word(node), lang)
        if not word or not lang:
            _add_descendants(store, parent_id, node.get("children"), stats, parent_lang)
            continue
        nid = node_id(lang, word)
        forms = [{"form": word, "dialect": dialect, "source": "wiktionary"}] if dialect else []
        store.add_entry(nid, lang, word, source="wiktionary", key=key_for(lang, word), forms=forms)
        borrowed = node.get("edge_type") == "borrowed" or any(k in (node.get("params") or {}) for k in ("bor", "lbor"))
        store.add_relation(nid, parent_id, _edge_type(lang, parent_lang, borrowed), "wiktionary")
        stats["descendant_edges"] += 1
        _add_descendants(store, nid, node.get("children"), stats, lang)


def _clean_gloss(g):
    # the parser lets following section headings ("\n\nInflection\n\nAlternative forms") leak into the last gloss
    return g.split("\n\n")[0].strip()


def _senses(defn):
    return [{"lang": "en", "gloss": _clean_gloss(g), "source": "wiktionary"} for g in defn.get("definitions") or [] if g and _clean_gloss(g)]


def _etymology_ids(lang, lemma, page):
    """One provisional id per etymology, so homographs on one page stay separate entries."""
    etys = [e for e in page.get("etymologies") or [] if e.get("definitions")] or (page.get("etymologies") or [])[:1]
    if len(etys) <= 1:
        return [(node_id(lang, lemma), e) for e in etys] or [(node_id(lang, lemma), {})]
    return [(f"{node_id(lang, lemma)}#{i}", e) for i, e in enumerate(etys, 1)]


def load_egyptian(store, stats):
    data = load_json(WIKT / "egyptian_lemmas_parsed_mwp.json")
    for lemma, page in data.items():
        lemma = re.sub(r"^Reconstruction:[^/]+/", "*", lemma)  # reconstruction pages: keep the form, marked *
        tla = _tla_ids(page.get("full_wikitext"))
        ids = _etymology_ids("egy", lemma, page)
        for eid, ety in ids:
            senses, forms, pos = [], [], None
            for defn in ety.get("definitions") or []:
                pos = pos or defn.get("part_of_speech")
                senses += _senses(defn)
                for alt in defn.get("alternative_forms") or []:
                    if alt.get("transliteration") or alt.get("hieroglyphs"):
                        forms.append({k: v for k, v in (("form", alt.get("transliteration")),
                                                         ("hieroglyphs", alt.get("hieroglyphs")),
                                                         ("date", alt.get("date")),
                                                         ("source", "wiktionary")) if v})
                for w in defn.get("derived_terms") or []:
                    w = clean_word(w if isinstance(w, str) else (w.get("word") or w.get("transliteration")))
                    if w:
                        store.add_entry(node_id("egy", w), "egy", w, source="wiktionary", key=egy_key(w))
                        store.add_relation(node_id("egy", w), eid, "derived_from", "wiktionary")
                        stats["derived_edges"] += 1
            store.add_entry(eid, "egy", lemma, source="wiktionary", key=egy_key(lemma), pos=pos, senses=senses,
                            forms=forms, sources={"wiktionary": {"page": lemma, **({"tla_ids": tla} if tla else {})}})
            for defn in ety.get("definitions") or []:
                _add_descendants(store, eid, defn.get("descendants"), stats)
        egy_tla = [i for i in tla if i.isdigit()]
        if len(egy_tla) == 1 and len(ids) == 1:
            store.entries[ids[0][0]]["sources"]["wiktionary"]["match"] = "tla_ref"
            store.merge(ids[0][0], f"egy:{egy_tla[0]}")
            stats["merged_via_tla_ref"] += 1
        elif egy_tla:
            stats["tla_ref_left_for_matcher"] += 1
        stats["egyptian_pages"] += 1
        stats["egyptian_entries"] += len(ids)


def _etymology_links(store, eid, wikitext, stats, own_lang):
    for sec in SECTION.findall(wikitext or ""):
        for m in ETYM_TEMPLATE.finditer(sec):
            kind, _, src_code, word = m.groups()
            lang, _ = wikt_lang(src_code)
            word = clean_word(word, lang)
            if not word or word == "-":
                continue
            did = node_id(lang, word)
            store.add_entry(did, lang, word, source="wiktionary", key=key_for(lang, word))
            rtype = _edge_type(own_lang, lang, kind.startswith(("bor", "lbor")))
            store.add_relation(eid, did, rtype, "wiktionary")
            stats["etymology_edges"] += 1


def load_other(store, stats, lang, filename):
    data = load_json(WIKT / filename)
    for lemma, page in data.items():
        lemma = re.sub(r"^Reconstruction:[^/]+/", "*", lemma)  # reconstruction pages: keep the form, marked *
        ids = _etymology_ids(lang, lemma, page)
        for eid, ety in ids:
            senses, pos = [], None
            for defn in ety.get("definitions") or []:
                pos = pos or defn.get("part_of_speech")
                senses += _senses(defn)
            store.add_entry(eid, lang, lemma, source="wiktionary", key=key_for(lang, lemma), pos=pos,
                            senses=senses, sources={"wiktionary": {"page": lemma}})
            # with one etymology the whole page's Etymology sections belong to it; otherwise use that etymology's text
            text = page.get("full_wikitext") if len(ids) == 1 else ety.get("etymology_text")
            _etymology_links(store, eid, text, stats, lang)
            for defn in ety.get("definitions") or []:
                _add_descendants(store, eid, defn.get("descendants"), stats, lang)
        stats[f"{lang}_pages"] += 1
        stats[f"{lang}_entries"] += len(ids)


def run(store):
    from collections import Counter
    stats = Counter()
    load_egyptian(store, stats)
    load_other(store, stats, "dem", "demotic_lemmas_parsed_mwp.json")
    load_other(store, stats, "cop", "coptic_lemmas_parsed_mwp.json")
    return dict(stats)
