"""
build_inheritance_networks.py – Build etymology inheritance networks.

Reads all three corpora (Egyptian, Coptic, Demotic) using the wiktionary3
parser and builds one ego-centric network per (word × etymology_index)
combination.  Each network captures:

  * Ancestor nodes  – parent words drawn from etymology templates.
  * Descendant nodes – words listed in the "Descendants" section.
  * Derived nodes    – words listed in the "Derived terms" section.
  * Related nodes    – words listed in the "Related terms" section.

Cross-linking: when a neighbour form matches a known corpus entry the node
is enriched with that entry's definitions, POS, and hieroglyphs.

Usage
-----
    python build_inheritance_networks.py                  # uses defaults
    python build_inheritance_networks.py --out /path/to/output.json
    python build_inheritance_networks.py --data-dir /path/to/Wiktionary

Output schema
-------------
A JSON array of network objects, each with:
{
  "network_id":          str,      # unique "NET#####"
  "root_lemma":          str,      # the word form
  "root_language":       str,      # display name, e.g. "Egyptian"
  "root_language_code":  str,      # Wiktionary lang code, e.g. "egy"
  "root_etymology_index": int,     # 1-based etymology index
  "nodes": [
    {
      "id":              str,      # unique "N#####" within this network
      "word":            str,
      "language":        str,      # display name
      "language_code":   str,      # Wiktionary lang code
      "part_of_speech":  str|null,
      "etymology_index": int|null,
      "definitions":     list[str],
      "hieroglyphs":     list[str],
      "role":            str,      # "root"|"ancestor"|"descendant"|"derived"|"related"
      "corpus_entry":    bool      # True if matched to a known corpus record
    },
    …
  ],
  "edges": [
    {
      "from":  str,   # node id
      "to":    str,   # node id
      "type":  str,   # see edge types below
      "notes": str
    },
    …
  ]
}

Edge types
----------
  INHERITED  – from {{inh}} / {{inherited}}
  BORROWED   – from {{bor}} / {{borrowed}}
  DERIVED    – from {{der}} / {{derived}}
  ROOT       – from {{root}}
  COMPONENT  – from {{compound}}
  AFFIXED    – from {{affix}}
  DESCENDS   – word appears in the Descendants section of the root
  DERIVES    – word appears in the Derived terms section of the root
  RELATED    – word appears in the Related terms section of the root
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

# Make sure the local parser module is importable.
sys.path.insert(0, os.path.dirname(__file__))

from parser import (
    WiktionaryParser,
    _extract_parent_relations,
)

# ---------------------------------------------------------------------------
# Language code / display-name tables
# ---------------------------------------------------------------------------

# Maps the display name used in the raw Wiktionary JSONs to a
# canonical Wiktionary BCP-47-style language code.
LANG_DISPLAY_TO_CODE: Dict[str, str] = {
    "Egyptian": "egy",
    "Demotic": "egx-dem",
    "Demotic Egyptian": "egx-dem",
    "Coptic": "cop",
}

# Reverse lookup used when enriching nodes from the corpus.
LANG_CODE_TO_DISPLAY: Dict[str, str] = {v: k for k, v in LANG_DISPLAY_TO_CODE.items()}
# Prefer canonical display names for duplicates.
LANG_CODE_TO_DISPLAY["egx-dem"] = "Demotic"


# ---------------------------------------------------------------------------
# Corpus index helpers
# ---------------------------------------------------------------------------


def _build_corpus_index(
    records: List[Dict],
) -> Dict[Tuple[str, str], List[Dict]]:
    """Return a mapping ``(word_lower, lang_code) → [record, …]``.

    The index allows fast look-up when connecting a parent / descendant word
    string to an actual corpus record.
    """
    index: Dict[Tuple[str, str], List[Dict]] = {}
    for rec in records:
        lang_code = LANG_DISPLAY_TO_CODE.get(rec["language"], rec["language"])
        key = (rec["word"].lower(), lang_code)
        index.setdefault(key, []).append(rec)
    return index


def _lookup(
    index: Dict[Tuple[str, str], List[Dict]],
    word: str,
    lang_code: str,
) -> Optional[Dict]:
    """Return the best matching corpus record or ``None``.

    Prefer the record with the fewest blank fields as a proxy for richness.
    """
    candidates = index.get((word.lower(), lang_code), [])
    if not candidates:
        return None
    return max(candidates, key=lambda r: bool(r["definitions"]) + bool(r["hieroglyphs"]))


# ---------------------------------------------------------------------------
# Network builder
# ---------------------------------------------------------------------------


class InheritanceNetworkBuilder:
    """Build one ego-centric inheritance network per (word × etymology_index)."""

    def __init__(self) -> None:
        self._net_counter = 0
        self._node_counter = 0

    # ------------------------------------------------------------------ ids

    def _new_net_id(self) -> str:
        nid = f"NET{self._net_counter:05d}"
        self._net_counter += 1
        return nid

    def _new_node_id(self) -> str:
        nid = f"N{self._node_counter:05d}"
        self._node_counter += 1
        return nid

    # -------------------------------------------------------------- node factory

    def _make_node(
        self,
        word: str,
        language: str,
        lang_code: str,
        role: str,
        *,
        pos: Optional[str] = None,
        etymology_index: Optional[int] = None,
        definitions: Optional[List[str]] = None,
        hieroglyphs: Optional[List[str]] = None,
        corpus_entry: bool = False,
    ) -> Dict:
        return {
            "id": self._new_node_id(),
            "word": word,
            "language": language,
            "language_code": lang_code,
            "part_of_speech": pos,
            "etymology_index": etymology_index,
            "definitions": definitions or [],
            "hieroglyphs": hieroglyphs or [],
            "role": role,
            "corpus_entry": corpus_entry,
        }

    # -------------------------------------------------------------- main build

    def build(
        self,
        records: List[Dict],
        corpus_index: Dict[Tuple[str, str], List[Dict]],
    ) -> List[Dict]:
        """Return a list of network objects.

        Parameters
        ----------
        records:
            Flat list of parser output records (all languages combined).
        corpus_index:
            Pre-built index from :func:`_build_corpus_index`.
        """
        networks: List[Dict] = []

        for root_rec in records:
            net = self._build_one(root_rec, corpus_index)
            if net is not None:
                networks.append(net)

        return networks

    # -------------------------------------------------------------- one network

    def _build_one(
        self,
        root_rec: Dict,
        index: Dict[Tuple[str, str], List[Dict]],
    ) -> Optional[Dict]:
        """Build a single network; return ``None`` if trivially empty."""
        word = root_rec["word"]
        language = root_rec["language"]
        lang_code = LANG_DISPLAY_TO_CODE.get(language, language)
        etym_idx = root_rec["etymology_index"]

        nodes: List[Dict] = []
        edges: List[Dict] = []

        # --- root node ---
        root_node = self._make_node(
            word=word,
            language=language,
            lang_code=lang_code,
            role="root",
            pos=root_rec.get("part_of_speech"),
            etymology_index=etym_idx,
            definitions=root_rec.get("definitions", []),
            hieroglyphs=root_rec.get("hieroglyphs", []),
            corpus_entry=True,
        )
        nodes.append(root_node)

        # --- ancestor nodes (from etymology templates) ---
        etym_raw = root_rec.get("_etymology_raw", root_rec.get("etymology_text", ""))
        parent_rels = _extract_parent_relations(etym_raw)

        for rel_info in parent_rels:
            p_word = rel_info["word"]
            p_lang = rel_info["lang"]
            p_display = LANG_CODE_TO_DISPLAY.get(p_lang, p_lang)
            p_corpus = _lookup(index, p_word, p_lang)

            anc_node = self._make_node(
                word=p_word,
                language=p_display,
                lang_code=p_lang,
                role="ancestor",
                pos=p_corpus.get("part_of_speech") if p_corpus else None,
                etymology_index=p_corpus.get("etymology_index") if p_corpus else None,
                definitions=p_corpus.get("definitions", []) if p_corpus else [],
                hieroglyphs=p_corpus.get("hieroglyphs", []) if p_corpus else [],
                corpus_entry=p_corpus is not None,
            )
            nodes.append(anc_node)
            edges.append({
                "from": anc_node["id"],
                "to": root_node["id"],
                "type": rel_info["rel"],
                "notes": f"{p_lang} → {lang_code}",
            })

        # --- descendant nodes ---
        for desc_word in root_rec.get("descendants", []):
            self._add_neighbour(
                desc_word, lang_code, "descendant", "DESCENDS",
                root_node, nodes, edges, index,
                edge_from=root_node["id"],
            )

        # --- derived-term nodes ---
        for der_word in root_rec.get("derived_terms", []):
            self._add_neighbour(
                der_word, lang_code, "derived", "DERIVES",
                root_node, nodes, edges, index,
                edge_from=root_node["id"],
            )

        # --- related-term nodes ---
        for rel_word in root_rec.get("related_terms", []):
            self._add_neighbour(
                rel_word, lang_code, "related", "RELATED",
                root_node, nodes, edges, index,
                edge_from=root_node["id"],
            )

        # Skip trivially empty networks (root-only, no connections).
        if len(nodes) == 1 and not edges:
            return None

        return {
            "network_id": self._new_net_id(),
            "root_lemma": word,
            "root_language": language,
            "root_language_code": lang_code,
            "root_etymology_index": etym_idx,
            "nodes": nodes,
            "edges": edges,
        }

    # -------------------------------------------------------------- helper

    def _add_neighbour(
        self,
        neighbour_word: str,
        root_lang_code: str,
        role: str,
        edge_type: str,
        root_node: Dict,
        nodes: List[Dict],
        edges: List[Dict],
        index: Dict[Tuple[str, str], List[Dict]],
        *,
        edge_from: str,
    ) -> None:
        """Add a single neighbour node + edge, skipping if already present."""
        # Avoid duplicates within this network.
        if any(n["word"] == neighbour_word and n["role"] == role for n in nodes):
            return

        # Try to find a corpus entry for this word in the root language first;
        # descendants may be in a different language, so also try without lang
        # filtering if no match is found.
        corpus = _lookup(index, neighbour_word, root_lang_code)

        # Guess display name from root language for same-language relations.
        lang_display = LANG_CODE_TO_DISPLAY.get(root_lang_code, root_lang_code)

        nb_node = self._make_node(
            word=neighbour_word,
            language=corpus.get("language", lang_display) if corpus else lang_display,
            lang_code=corpus
                and LANG_DISPLAY_TO_CODE.get(corpus["language"], root_lang_code)
                or root_lang_code,
            role=role,
            pos=corpus.get("part_of_speech") if corpus else None,
            etymology_index=corpus.get("etymology_index") if corpus else None,
            definitions=corpus.get("definitions", []) if corpus else [],
            hieroglyphs=corpus.get("hieroglyphs", []) if corpus else [],
            corpus_entry=corpus is not None,
        )
        nodes.append(nb_node)
        edges.append({
            "from": edge_from,
            "to": nb_node["id"],
            "type": edge_type,
            "notes": f"{neighbour_word}",
        })


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_corpora(data_dir: str) -> List[Dict]:
    """Parse all three corpora and return a flat list of records.

    Each record gets an additional ``"_etymology_raw"`` key with the raw
    wikitext of the etymology block so that :func:`_extract_parent_relations`
    can be called on it (the parser already sets ``etymology_text`` to cleaned
    plain text, which strips template names).
    """
    p = WiktionaryParser()
    all_records: List[Dict] = []

    for fname, lang in [
        ("egyptian_lemmas.json", "Egyptian"),
        ("coptic_lemmas.json", "Coptic"),
        ("demotic_lemmas.json", "Demotic"),
    ]:
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            print(f"  [warn] {path} not found – skipping", file=sys.stderr)
            continue

        with open(path, encoding="utf-8") as fh:
            wikt = json.load(fh)

        print(f"  Parsing {lang} ({len(wikt)} entries)…")
        for title, entry in wikt.items():
            wikitext = entry.get("full_wikitext", "")
            records = p.parse(wikitext, title, lang)
            # Attach raw etymology text (the parser stores it cleaned; we need
            # the raw wikitext for template re-parsing in _extract_parent_relations).
            # We pull it directly from the wikitext via the same internal helper.
            from parser import (  # noqa: PLC0415
                _extract_language_section,
                _split_sections,
                _find_sections,
                _parse_etymology_number,
                WiktionaryParser as _WP,
            )
            lang_text = _extract_language_section(wikitext, lang) or ""
            _sections = _split_sections(lang_text)

            # Build a quick map: etymology_index → raw preamble text.
            etym_raw_map: Dict[int, str] = {}
            numbered = _find_sections(_sections, level=3, title_prefix="etymology ")
            if numbered:
                for etym_title, etym_content in numbered:
                    idx = _parse_etymology_number(etym_title)
                    m = __import__("re").search(r"^(={2,6})", etym_content, __import__("re").MULTILINE)
                    preamble = etym_content[: m.start()] if m else etym_content
                    etym_raw_map[idx] = preamble
            else:
                etym_flat = _find_sections(_sections, level=3, title_prefix="etymology", exact=True)
                etym_raw_map[1] = etym_flat[0][1] if etym_flat else lang_text

            for rec in records:
                rec["_etymology_raw"] = etym_raw_map.get(rec["etymology_index"], "")
            all_records.extend(records)

    print(f"  Total records: {len(all_records)}")
    return all_records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    default_data_dir = os.path.join(
        os.path.dirname(__file__),
        "..",
        "Data Collection and Management",
        "Wiktionary",
    )
    default_out = os.path.join(default_data_dir, "inheritance_networks.json")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=default_data_dir, help="Directory containing the *_lemmas.json files")
    ap.add_argument("--out", default=default_out, help="Output JSON path")
    args = ap.parse_args()

    data_dir = os.path.normpath(args.data_dir)
    out_path = os.path.normpath(args.out)

    print("Building inheritance networks")
    print("=" * 60)
    print(f"  Data dir : {data_dir}")
    print(f"  Output   : {out_path}")
    print()

    # 1. Parse all corpora.
    print("Loading corpora…")
    records = _load_corpora(data_dir)

    # 2. Build corpus index for cross-linking.
    print("Building corpus index…")
    index = _build_corpus_index(records)

    # 3. Build networks.
    print("Building networks…")
    builder = InheritanceNetworkBuilder()
    networks = builder.build(records, index)

    # 4. Write output.
    print(f"Writing {len(networks)} networks to {out_path}…")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(networks, fh, ensure_ascii=False, indent=2)

    total_nodes = sum(len(n["nodes"]) for n in networks)
    total_edges = sum(len(n["edges"]) for n in networks)

    # Edge-type breakdown.
    type_counts: Dict[str, int] = {}
    for net in networks:
        for edge in net["edges"]:
            t = edge["type"]
            type_counts[t] = type_counts.get(t, 0) + 1

    print()
    print("=" * 60)
    print(f"Done.  {len(networks)} networks, {total_nodes} nodes, {total_edges} edges")
    print()
    print("Edge type breakdown:")
    for etype, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {etype:<12s}  {cnt:6d}")


if __name__ == "__main__":
    main()
