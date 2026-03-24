"""
test_parser.py – Unit tests for parser.py.

Run with:  python -m pytest test_parser.py -v
       or: python test_parser.py
"""

from __future__ import annotations

import sys
import os
import unittest

# Ensure local modules are importable when running from within wiktionary3/
sys.path.insert(0, os.path.dirname(__file__))

from parser import (
    WiktionaryParser,
    _split_sections,
    _extract_language_section,
    _extract_definitions,
    _extract_linked_terms,
    _extract_parent_words,
    _clean_definition,
    _clean_etymology_text,
    _parse_etymology_number,
)


# ---------------------------------------------------------------------------
# Sample wikitext fixtures
# ---------------------------------------------------------------------------

# Minimal Egyptian entry with multiple etymologies (mirrors the real ꜣ page).
EGYPTIAN_MULTI_ETYM = r"""==Egyptian==
[[File:Egyptian vulture.jpg|thumb|vulture]]

===Pronunciation===
{{egy-IPA-E}}

===Etymology 1===
Possibly from {{inh|egy|afa-pro|*ʔay-||bird of prey}}.

====Noun====
{{egy-noun|m|head=A}}

# the [[Egyptian vulture]] ({{taxfmt|Neophron percnopterus|species}})
# a [[bird]] in general

=====Alternative forms=====
{{egy-hieroforms|A-Z1:H_SPACE|read1=ꜣ}}

=====Derived terms=====
* {{l|egy|ꜣbd}}
* {{l|egy|ꜣmw}}

=====Descendants=====
* {{desc|cop|ⲁ}}

===Etymology 2===

====Particle====
{{egy-part|enclitic|head=A}}

# {{ng|intensifying particle}}, [[indeed]]
# {{lb|egy|Neo-Middle Egyptian}} [[also]], [[and]]

=====Derived terms=====
{{col|egy|nfr ꜣ|ḥꜣ}}

===See also===
* {{l|egy|𓄿}}

===References===
* {{R:egy:Faulkner|1}}
"""

# Coptic entry with single etymology and POS at L3.
COPTIC_FLAT = r"""==Coptic==

===Pronunciation===
* {{IPA|cop|/a/}}

===Etymology===
From {{inh|cop|egy|ꜣ|t=vulture}}.

===Noun===
{{cop-noun|m}}

# [[bird]]
# [[eagle]]

====Derived terms====
* {{l|cop|ⲁⲗⲉⲧ}}

====Related terms====
* {{l|cop|ⲁⲗⲟⲩ}}
"""

# Entry with no target-language section.
NO_TARGET_LANG = r"""==English==

===Noun===
# A [[word]].

==French==

===Noun===
# Un [[mot]].
"""

# Demotic entry (very sparse – as found in practice).
DEMOTIC_ENTRY = r"""==Demotic==

===Noun===
# [[house]]
# [[temple]]

====Derived terms====
[[pr-ꜥꜣ]]
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSplitSections(unittest.TestCase):
    def test_finds_all_levels(self):
        text = "==L2==\ncontent2\n===L3===\ncontent3\n====L4====\ncontent4\n"
        sections = _split_sections(text)
        titles = [t for _, t, _ in sections]
        self.assertIn("L2", titles)
        self.assertIn("L3", titles)
        self.assertIn("L4", titles)

    def test_content_ends_at_peer_heading(self):
        text = "===A===\ntext A\n===B===\ntext B\n"
        sections = _split_sections(text)
        # Section A's content should NOT include "text B"
        a_content = next(c for _, t, c in sections if t == "A")
        self.assertNotIn("text B", a_content)
        self.assertIn("text A", a_content)

    def test_content_includes_deeper_subsections(self):
        text = "===Etym===\nfoo\n====Noun====\nbar\n"
        sections = _split_sections(text)
        etym_content = next(c for _, t, c in sections if t == "Etym")
        self.assertIn("bar", etym_content)

    def test_empty_input(self):
        self.assertEqual(_split_sections(""), [])

    def test_no_headings(self):
        self.assertEqual(_split_sections("just text\nno headings\n"), [])


class TestExtractLanguageSection(unittest.TestCase):
    def test_extracts_egyptian(self):
        section = _extract_language_section(EGYPTIAN_MULTI_ETYM, "Egyptian")
        self.assertIsNotNone(section)
        self.assertIn("Etymology 1", section)

    def test_extracts_coptic(self):
        section = _extract_language_section(COPTIC_FLAT, "Coptic")
        self.assertIsNotNone(section)
        self.assertIn("Noun", section)

    def test_missing_language_returns_none(self):
        section = _extract_language_section(NO_TARGET_LANG, "Egyptian")
        self.assertIsNone(section)

    def test_demotic_variant(self):
        section = _extract_language_section(DEMOTIC_ENTRY, "Demotic")
        self.assertIsNotNone(section)

    def test_demotic_egyptian_alias(self):
        # "Demotic Egyptian" should fall back to finding "Demotic" section.
        section = _extract_language_section(DEMOTIC_ENTRY, "Demotic Egyptian")
        self.assertIsNotNone(section)


class TestExtractDefinitions(unittest.TestCase):
    def test_basic_hashes(self):
        text = "# first definition\n# second definition\n"
        defs = _extract_definitions(text)
        self.assertEqual(len(defs), 2)

    def test_skips_sub_definitions(self):
        text = "# main def\n## sub def\n# another main\n"
        defs = _extract_definitions(text)
        self.assertEqual(len(defs), 2)
        self.assertNotIn("sub def", " ".join(defs))

    def test_strips_templates(self):
        text = "# {{lb|egy|intransitive}} to [[enter]]\n"
        defs = _extract_definitions(text)
        self.assertEqual(len(defs), 1)
        self.assertIn("intransitive", defs[0])
        self.assertIn("enter", defs[0])

    def test_empty_lines_ignored(self):
        text = "\n\n# valid\n\n"
        defs = _extract_definitions(text)
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0], "valid")


class TestExtractLinkedTerms(unittest.TestCase):
    def test_l_template(self):
        text = "* {{l|egy|ꜣbd}}\n* {{l|egy|ꜣmw}}\n"
        terms = _extract_linked_terms(text)
        self.assertIn("ꜣbd", terms)
        self.assertIn("ꜣmw", terms)

    def test_desc_template(self):
        text = "* {{desc|cop|ⲁ}}\n"
        terms = _extract_linked_terms(text)
        self.assertIn("ⲁ", terms)

    def test_col_template(self):
        text = "{{col|egy|nfr ꜣ|ḥꜣ}}\n"
        terms = _extract_linked_terms(text)
        self.assertIn("nfr ꜣ", terms)
        self.assertIn("ḥꜣ", terms)

    def test_wikilinks(self):
        text = "* [[pr-ꜥꜣ]]\n* [[word|display]]\n"
        terms = _extract_linked_terms(text)
        self.assertIn("pr-ꜥꜣ", terms)
        # For [[word|display]], the link *target* (canonical lemma) is extracted.
        self.assertIn("word", terms)

    def test_deduplication(self):
        text = "* {{l|egy|foo}}\n* {{l|egy|foo}}\n"
        terms = _extract_linked_terms(text)
        self.assertEqual(terms.count("foo"), 1)

    def test_skips_category_links(self):
        text = "[[Category:Egyptian lemmas]]\n"
        terms = _extract_linked_terms(text)
        self.assertNotIn("Category:Egyptian lemmas", terms)


class TestExtractParentWords(unittest.TestCase):
    def test_inh_template(self):
        text = "From {{inh|cop|egy|ꜣ|t=vulture}}."
        parents = _extract_parent_words(text)
        self.assertTrue(any("ꜣ" in pw for pw in parents))
        self.assertTrue(any("egy" in pw for pw in parents))

    def test_bor_template(self):
        text = "Borrowed from {{bor|cop|grc|ἄγγελος}}."
        parents = _extract_parent_words(text)
        self.assertTrue(any("ἄγγελος" in pw for pw in parents))

    def test_der_template(self):
        text = "From {{der|egy|afa-pro|*ʔay-}}."
        parents = _extract_parent_words(text)
        self.assertTrue(any("*ʔay-" in pw for pw in parents))

    def test_cog_is_not_parent(self):
        text = "Compare {{cog|sem-pro|*ʔayy-}}."
        parents = _extract_parent_words(text)
        self.assertEqual(parents, [])

    def test_empty_input(self):
        self.assertEqual(_extract_parent_words(""), [])


class TestCleanDefinition(unittest.TestCase):
    def test_lb_template(self):
        result = _clean_definition("{{lb|egy|intransitive}} to enter")
        self.assertIn("intransitive", result)
        self.assertIn("to enter", result)

    def test_ng_template(self):
        result = _clean_definition("{{ng|intensifying particle}}, indeed")
        self.assertIn("intensifying particle", result)

    def test_wikilink(self):
        result = _clean_definition("the [[Egyptian vulture]]")
        self.assertIn("Egyptian vulture", result)
        self.assertNotIn("[[", result)

    def test_taxfmt(self):
        result = _clean_definition("{{taxfmt|Neophron percnopterus|species}}")
        self.assertIn("Neophron percnopterus", result)

    def test_defdate(self):
        result = _clean_definition("a bird {{defdate|11th Dynasty}}")
        self.assertIn("11th Dynasty", result)


class TestParseEtymologyNumber(unittest.TestCase):
    def test_numbered(self):
        self.assertEqual(_parse_etymology_number("Etymology 1"), 1)
        self.assertEqual(_parse_etymology_number("Etymology 2"), 2)
        self.assertEqual(_parse_etymology_number("Etymology 10"), 10)

    def test_unnumbered(self):
        self.assertEqual(_parse_etymology_number("Etymology"), 1)


class TestWiktionaryParser(unittest.TestCase):
    def setUp(self):
        self.parser = WiktionaryParser()

    # ------------------------------------------------------------------
    # Egyptian multi-etymology
    # ------------------------------------------------------------------

    def test_egyptian_returns_records(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        self.assertGreater(len(records), 0)

    def test_egyptian_has_two_etymology_indices(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        indices = {r["etymology_index"] for r in records}
        self.assertIn(1, indices)
        self.assertIn(2, indices)

    def test_egyptian_noun_record(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        noun_records = [r for r in records if r["part_of_speech"].lower() == "noun"]
        self.assertGreater(len(noun_records), 0)
        noun = noun_records[0]
        self.assertEqual(noun["word"], "ꜣ")
        self.assertEqual(noun["language"], "Egyptian")
        self.assertEqual(noun["etymology_index"], 1)
        self.assertGreater(len(noun["definitions"]), 0)

    def test_egyptian_noun_definitions(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        noun = next(r for r in records if r["part_of_speech"].lower() == "noun")
        defs = noun["definitions"]
        self.assertGreater(len(defs), 0)
        combined = " ".join(defs).lower()
        self.assertIn("vulture", combined)

    def test_egyptian_noun_derived_terms(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        noun = next(r for r in records if r["part_of_speech"].lower() == "noun")
        self.assertIn("ꜣbd", noun["derived_terms"])

    def test_egyptian_noun_descendants(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        noun = next(r for r in records if r["part_of_speech"].lower() == "noun")
        self.assertIn("ⲁ", noun["descendants"])

    def test_egyptian_parent_words(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        noun = next(r for r in records if r["part_of_speech"].lower() == "noun")
        self.assertTrue(
            any("afa-pro" in pw for pw in noun["parent_words"]),
            f"Expected 'afa-pro' in parent_words, got: {noun['parent_words']}",
        )

    def test_egyptian_particle_record(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        particle_records = [r for r in records if r["part_of_speech"].lower() == "particle"]
        self.assertGreater(len(particle_records), 0)
        particle = particle_records[0]
        self.assertEqual(particle["etymology_index"], 2)

    def test_egyptian_particle_derived_terms(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        particle = next(r for r in records if r["part_of_speech"].lower() == "particle")
        # col template should be unpacked
        self.assertTrue(
            any("ḥꜣ" in t for t in particle["derived_terms"]),
            f"Expected ḥꜣ in derived_terms: {particle['derived_terms']}",
        )

    # ------------------------------------------------------------------
    # Coptic flat layout
    # ------------------------------------------------------------------

    def test_coptic_returns_records(self):
        records = self.parser.parse(COPTIC_FLAT, "ⲁ", "Coptic")
        self.assertGreater(len(records), 0)

    def test_coptic_single_etymology_index(self):
        records = self.parser.parse(COPTIC_FLAT, "ⲁ", "Coptic")
        self.assertTrue(all(r["etymology_index"] == 1 for r in records))

    def test_coptic_noun_definitions(self):
        records = self.parser.parse(COPTIC_FLAT, "ⲁ", "Coptic")
        noun = next(r for r in records if r["part_of_speech"].lower() == "noun")
        defs = noun["definitions"]
        self.assertGreater(len(defs), 0)
        combined = " ".join(defs).lower()
        self.assertIn("bird", combined)

    def test_coptic_parent_from_etymology(self):
        records = self.parser.parse(COPTIC_FLAT, "ⲁ", "Coptic")
        noun = next(r for r in records if r["part_of_speech"].lower() == "noun")
        self.assertTrue(
            any("egy" in pw for pw in noun["parent_words"]),
            f"Expected egy parent, got: {noun['parent_words']}",
        )

    def test_coptic_derived_terms(self):
        records = self.parser.parse(COPTIC_FLAT, "ⲁ", "Coptic")
        noun = next(r for r in records if r["part_of_speech"].lower() == "noun")
        self.assertIn("ⲁⲗⲉⲧ", noun["derived_terms"])

    def test_coptic_related_terms(self):
        records = self.parser.parse(COPTIC_FLAT, "ⲁ", "Coptic")
        noun = next(r for r in records if r["part_of_speech"].lower() == "noun")
        self.assertIn("ⲁⲗⲟⲩ", noun["related_terms"])

    # ------------------------------------------------------------------
    # Demotic
    # ------------------------------------------------------------------

    def test_demotic_returns_records(self):
        records = self.parser.parse(DEMOTIC_ENTRY, "pr", "Demotic")
        self.assertGreater(len(records), 0)

    def test_demotic_definitions(self):
        records = self.parser.parse(DEMOTIC_ENTRY, "pr", "Demotic")
        noun = records[0]
        self.assertGreater(len(noun["definitions"]), 0)
        combined = " ".join(noun["definitions"]).lower()
        self.assertTrue("house" in combined or "temple" in combined)

    # ------------------------------------------------------------------
    # Missing language section
    # ------------------------------------------------------------------

    def test_wrong_language_empty(self):
        records = self.parser.parse(NO_TARGET_LANG, "test", "Egyptian")
        self.assertEqual(records, [])

    # ------------------------------------------------------------------
    # Record schema completeness
    # ------------------------------------------------------------------

    def test_record_schema_keys(self):
        required_keys = {
            "word",
            "language",
            "part_of_speech",
            "etymology_index",
            "etymology_text",
            "parent_words",
            "definitions",
            "derived_terms",
            "descendants",
            "related_terms",
        }
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        self.assertGreater(len(records), 0)
        for rec in records:
            for key in required_keys:
                self.assertIn(key, rec, f"Missing key {key!r} in record")

    def test_parent_words_list(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        for rec in records:
            self.assertIsInstance(rec["parent_words"], list)

    def test_definitions_list(self):
        records = self.parser.parse(EGYPTIAN_MULTI_ETYM, "ꜣ", "Egyptian")
        for rec in records:
            self.assertIsInstance(rec["definitions"], list)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
