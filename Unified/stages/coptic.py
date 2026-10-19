"""Coptic layer: BBAW Comprehensive Coptic Lexicon (backbone) + Coptic Dictionary Online + ORAEC links."""
import re
import xml.etree.ElementTree as ET

from schema import ROOT, load_json
from translit import coptic_key

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

BBAW_XML = ROOT / "BBAW Coptic Lexicon" / "Comprehensive_Coptic_Lexicon-v1.2-2020.xml"
CDO_JSON = ROOT / "Coptic Dictionary Online" / "all_lemmas_parsed.json"
ORAEC_JSON = ROOT / "ORAEC" / "coptic_etymologies_enhanced.json"


def _text(el):
    return "".join(el.itertext()).strip() if el is not None else None


def _parse_bibl(bibl):
    """'CD 2a; CED 12; KoptHWb 2, 484' -> [{'work': 'CD', 'loc': '2a'}, ...]"""
    refs = []
    for part in (bibl or "").split(";"):
        part = part.strip()
        m = re.match(r"(\S+)\s+(.+)", part)
        if m:
            refs.append({"work": m.group(1), "loc": m.group(2), "source": "bbaw"})
        elif part:
            refs.append({"work": part, "source": "bbaw"})
    return refs


def load_bbaw(store):
    root = ET.parse(BBAW_XML).getroot()
    body = root.find(f"{TEI}text/{TEI}body")
    lemma_index = {}  # coptic key -> first entry id, for resolving xr targets
    pending_xr = []

    def handle_entry(entry, head_id=None):
        cid = entry.get(XML_ID)
        eid = f"cop:{cid}"
        forms, lemma = [], None
        for form in entry.findall(f"{TEI}form"):
            orth = _text(form.find(f"{TEI}orth"))
            if not orth:
                continue
            if form.get("type") == "lemma" and lemma is None:
                lemma = orth
            item = {"form": orth, "source": "bbaw"}
            dialect = _text(form.find(f"{TEI}usg"))
            if dialect:
                item["dialect"] = dialect
            if form.get("type") and form.get("type") != "lemma":
                item["type"] = form.get("type")
            forms.append(item)
        gram = entry.find(f"{TEI}gramGrp")
        senses, refs = [], []
        for sense in entry.findall(f"{TEI}sense"):
            for cit in sense.iter(f"{TEI}cit"):
                if cit.get("type") != "translation":
                    continue
                for q in cit.findall(f"{TEI}quote"):
                    if _text(q):
                        senses.append({"lang": q.get(XML_LANG), "gloss": _text(q), "source": "bbaw"})
                refs += _parse_bibl(_text(cit.find(f"{TEI}bibl")))
        store.add_entry(
            eid, "cop", lemma, source="bbaw",
            key=coptic_key(lemma),
            pos=_text(gram.find(f"{TEI}pos")) if gram is not None else None,
            gender=_text(gram.find(f"{TEI}gen")) if gram is not None else None,
            forms=forms, senses=senses, refs=refs,
            sources={"bbaw": {"id": cid, **({"type": entry.get("type")} if entry.get("type") else {})}},
        )
        if lemma:
            lemma_index.setdefault(coptic_key(lemma), eid)

        etym = entry.find(f"{TEI}etym")
        if etym is not None:
            grl = {r.get("type").split("::")[-1]: _text(r) for r in etym.findall(f"{TEI}ref") if "greek_lemma" in (r.get("type") or "")}
            if grl.get("grl_ID"):
                gid = f"grc:{grl['grl_ID']}"
                store.add_entry(
                    gid, "grc", grl.get("grl_lemma"), source="ddglc",
                    pos=grl.get("grl_pos"),
                    senses=[{"lang": "en", "gloss": grl["grl_meaning"], "source": "ddglc"}] if grl.get("grl_meaning") else [],
                    refs=[{"work": grl["grl_ref"], "source": "ddglc"}] if grl.get("grl_ref") else [],
                )
                store.add_relation(eid, gid, "borrowed_from", "bbaw")
            note = _text(etym.find(f"{TEI}note"))
            if note:
                store.entries[store.resolve(eid)].setdefault("etym_notes", []).append({"text": note, "source": "bbaw"})
            wcn = {r.get("type"): r.get("target", "").lstrip("#") for r in etym.findall(f"{TEI}ref") if (r.get("type") or "").startswith("WCN")}
            if wcn:
                store.entries[store.resolve(eid)]["sources"]["bbaw"]["wcn"] = wcn

        for xr in entry.findall(f"{TEI}xr"):
            for ref in xr.findall(f"{TEI}ref"):
                target = (ref.get("target") or "").lstrip("#")
                if target:
                    pending_xr.append((eid, target, xr.get("type")))

        if head_id and entry.get("type") == "compound":
            store.add_relation(eid, head_id, "derived_from", "bbaw")
        return eid

    for child in body:
        if child.tag == f"{TEI}superEntry":
            head = None
            for entry in child.findall(f"{TEI}entry"):
                eid = handle_entry(entry, head)
                if head is None and entry.get("type") != "compound":
                    head = eid
        elif child.tag == f"{TEI}entry":
            handle_entry(child)

    unresolved = 0
    for eid, target, xtype in pending_xr:
        dst = f"cop:{target}" if re.fullmatch(r"C\d+", target) else lemma_index.get(coptic_key(target))
        if dst:
            store.add_relation(eid, dst, "see_also", "bbaw", note=xtype)
        else:
            unresolved += 1
    return {"bbaw_entries": sum(1 for e in store.entries.values() if "bbaw" in e["sources"]), "bbaw_xr_unresolved": unresolved}, lemma_index


def _cdo_cf_terms(raw):
    """Parse 'cf.\\nⲁⲛⲍⲏⲃⲉ\\n school, cf.\\nⲁⲛⲁϩⲱⲣ\\n treasury' -> [('ⲁⲛⲍⲏⲃⲉ', 'school'), ('ⲁⲛⲁϩⲱⲣ', 'treasury')]"""
    if "cf." not in raw:
        return []
    tail = raw.split("cf.", 1)[1]
    out = []
    for chunk in tail.split("cf."):
        lines = [l.strip(" ,;") for l in chunk.strip().split("\n") if l.strip(" ,;")]
        if lines and re.search(r"[Ⲁ-⳿Ϣ-ϯ]", lines[0]):
            out.append((lines[0], lines[1] if len(lines) > 1 else None))
    return out


def load_cdo(store, lemma_index):
    stats = {"cdo_entries": 0, "cdo_examples": 0, "cdo_provisional_links": 0}
    for x in load_json(CDO_JSON):
        cid = x["tla"]
        eid = f"cop:{cid}"
        senses = []
        for s in x.get("senses") or []:
            for lang in ("en", "fr", "de"):
                if s.get(lang):
                    senses.append({"lang": lang, "gloss": s[lang], "source": "cdo"})
        forms = [{"form": l["Form"], "dialect": l.get("Dialect"), "source": "cdo"} for l in x.get("lemmas") or [] if l.get("Form") and l.get("Dialect") != "–"]
        e = store.add_entry(eid, "cop", x.get("title"), source="cdo", key=coptic_key(x.get("title")),
                            senses=senses, forms=forms, sources={"cdo": {"tla": cid}})
        if x.get("examples"):
            e["sources"]["cdo"]["examples"] = len(x["examples"])
            stats["cdo_examples"] += len(x["examples"])
        stats["cdo_entries"] += 1

        ety = x.get("etymology")
        if not ety:
            continue
        main = ety.get("main") or {}
        dem = main.get("demotic") if main.get("demotic") not in (None, "NA") else None
        hie = main.get("hieroglyphic") if main.get("hieroglyphic") not in (None, "NA") else None
        e["sources"]["cdo"]["etymology"] = {k: v for k, v in (("demotic", dem), ("hieroglyphic", hie)) if v}
        for term, gloss in _cdo_cf_terms(ety.get("raw", "")):
            dst = lemma_index.get(coptic_key(term))
            if dst:
                store.add_relation(eid, dst, "see_also", "cdo", note="cf")
    return stats


def load_oraec(store):
    stats = {"oraec_links": 0}
    for x in load_json(ORAEC_JSON):
        cop = f"cop:{x['coptic_id']}"
        egy = f"egy:{x['egyptian_id']}" if x.get("egyptian_id") else None
        dem = f"dem:d{x['demotic_id']}" if x.get("demotic_id") else None
        if egy:
            store.add_entry(egy, "egy", x.get("egyptian_word"), source="oraec", sources={"tla": {"id": x["egyptian_id"]}})
        if dem:
            store.add_entry(dem, "dem", x.get("demotic_word"), source="oraec", sources={"tla": {"id": "d" + x["demotic_id"]}})
        if dem:
            store.add_relation(cop, dem, "descends_from", "oraec")
            if egy:
                store.add_relation(dem, egy, "descends_from", "oraec")
        elif egy:
            store.add_relation(cop, egy, "descends_from", "oraec")
        stats["oraec_links"] += 1
    return stats


def link_cdo_without_ids(store):
    """CDO etymologies that ORAEC lacks: create provisional egy:cdo:/dem:cdo: entries keyed by transliteration."""
    linked = {r["src"] for r in store.relations.values() if r["type"] == "descends_from" and "oraec" in r["sources"]}
    n = 0
    for e in list(store.entries.values()):
        ety = e["sources"].get("cdo", {}).get("etymology")
        if not ety or e["id"] in linked:
            continue
        dem = f"dem:cdo:{ety['demotic']}" if ety.get("demotic") else None
        egy = f"egy:cdo:{ety['hieroglyphic']}" if ety.get("hieroglyphic") else None
        if dem:
            store.add_entry(dem, "dem", ety["demotic"], source="cdo")
            store.add_relation(e["id"], dem, "descends_from", "cdo")
            if egy:
                store.add_entry(egy, "egy", ety["hieroglyphic"], source="cdo")
                store.add_relation(dem, egy, "descends_from", "cdo")
        elif egy:
            store.add_entry(egy, "egy", ety["hieroglyphic"], source="cdo")
            store.add_relation(e["id"], egy, "descends_from", "cdo")
        n += 1
    return {"cdo_provisional_links": n}


def confirm_cdo_against_oraec(store):
    """Where CDO's etymology names the same words ORAEC linked by ID, credit CDO on that relation too."""
    agree = 0
    for r in store.relations.values():
        if r["type"] != "descends_from" or "oraec" not in r["sources"] or not r["src"].startswith("cop:"):
            continue
        ety = store.entries.get(r["src"], {}).get("sources", {}).get("cdo", {}).get("etymology")
        dst = store.entries.get(r["dst"])
        if ety and dst and dst.get("lemma") in (ety.get("demotic"), ety.get("hieroglyphic")):
            r["sources"].append("cdo")
            agree += 1
    return {"cdo_agrees_with_oraec": agree}


def run(store):
    stats, lemma_index = load_bbaw(store)
    stats.update(load_cdo(store, lemma_index))
    stats.update(load_oraec(store))
    stats.update(confirm_cdo_against_oraec(store))
    stats.update(link_cdo_without_ids(store))
    return stats
