"""
parser.py – Wikitext parser for Coptic / Egyptian / Demotic Wiktionary entries.

Design goals
------------
* Handle all Wiktionary section-level variants observed across 50–100 sample
  pages (single/multiple etymologies, POS at L3 or L4, derived-terms at L4/L5).
* Never hallucinate – if a field cannot be reliably extracted, leave it empty.
* Preserve full Unicode.
* Return a list of flat dicts matching the target schema; one dict per
  (word × etymology × part-of-speech) combination.

Output record schema
--------------------
{
    "word":            str,
    "language":        str,
    "part_of_speech":  str,
    "etymology_index": int,          # 1-based; 1 when no numbered etymologies
    "etymology_text":  str,
    "parent_words":    list[str],    # "word (lang-code)" strings
    "definitions":     list[str],
    "derived_terms":   list[str],
    "descendants":     list[str],
    "related_terms":   list[str],
}
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

import mwparserfromhell

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# Wiktionary part-of-speech headings that we recognise (lower-cased).
POS_NAMES: frozenset[str] = frozenset(
    {
        "noun",
        "verb",
        "particle",
        "symbol",
        "pronoun",
        "preposition",
        "adjective",
        "adverb",
        "conjunction",
        "determiner",
        "interjection",
        "proper noun",
        "article",
        "numeral",
        "suffix",
        "prefix",
        "affix",
        "root",
        "letter",
        "phrase",
        "idiom",
        "proverb",
        "classifier",
        "postposition",
        "circumposition",
        "interfix",
        "infix",
        "circumfix",
        "prepositional phrase",
        "verbal noun",
        "infinitive",
        "participle",
        "gerund",
    }
)

# Heading words (lower-cased) whose sections should be skipped entirely.
NON_CONTENT_SECTIONS: frozenset[str] = frozenset(
    {
        "pronunciation",
        "see also",
        "references",
        "further reading",
        "anagrams",
        "external links",
        "inflection",
        "declension",
        "conjugation",
        "alternative forms",
        "quotations",
    }
)

# Etymology-template names whose first (positional 2nd) param is a parent word.
INHERITANCE_TEMPLATES: frozenset[str] = frozenset(
    {"inh", "inherited", "bor", "borrowed", "der", "derived", "root", "affix"}
)

# Link / list templates used in derived-terms / descendants / related sections.
LINK_TEMPLATES: frozenset[str] = frozenset(
    {"l", "link", "l/", "link/", "m", "mention", "m+"}
)
DESCENDANT_TEMPLATES: frozenset[str] = frozenset(
    {"desc", "descendant", "desctree", "desc-tree"}
)
COLUMN_TEMPLATES: frozenset[str] = frozenset(
    {"col", "col1", "col2", "col3", "col4", "col5", "columns"}
)

# ---------------------------------------------------------------------------
# Section splitting helpers
# ---------------------------------------------------------------------------

# Compiled regex to match MediaWiki headings at any depth 2–6.
_HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)


def _split_sections(text: str) -> List[Tuple[int, str, str]]:
    """Return ``(level, title, content)`` for every heading in *text*.

    *content* runs from the character after the heading's newline to the
    character before the next heading at the **same or higher** (smaller-
    number) level.  Content therefore includes any deeper sub-sections.
    """
    matches = list(_HEADING_RE.finditer(text))
    result: List[Tuple[int, str, str]] = []

    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()

        # Content starts immediately after the heading line.
        content_start = m.end()
        if content_start < len(text) and text[content_start] == "\n":
            content_start += 1

        # Content ends at the next heading with level ≤ current level.
        content_end = len(text)
        for j in range(i + 1, len(matches)):
            nxt_level = len(matches[j].group(1))
            if nxt_level <= level:
                content_end = matches[j].start()
                break

        content = text[content_start:content_end]
        result.append((level, title, content))

    return result


def _find_sections(
    sections: List[Tuple[int, str, str]],
    level: int,
    title_prefix: Optional[str] = None,
    exact: bool = False,
) -> List[Tuple[str, str]]:
    """Filter *sections* by level and optional title match.

    Returns ``(title, content)`` pairs.
    """
    out = []
    for lvl, title, content in sections:
        if lvl != level:
            continue
        if title_prefix is not None:
            t_lower = title.lower()
            needle = title_prefix.lower()
            if exact:
                if t_lower != needle:
                    continue
            else:
                if not t_lower.startswith(needle):
                    continue
        out.append((title, content))
    return out


def _extract_language_section(wikitext: str, language: str) -> Optional[str]:
    """Return the text of the *language* L2 section, or ``None``.

    Handles common spelling variants:
      * "Demotic" / "Demotic Egyptian"
      * "Egyptian"
      * "Coptic"
    """
    variants = {language}
    lo = language.lower()
    if lo == "demotic":
        variants.add("Demotic Egyptian")
    elif lo == "demotic egyptian":
        variants.add("Demotic")

    for lvl, title, content in _split_sections(wikitext):
        if lvl == 2 and title.strip() in variants:
            return content

    return None


# ---------------------------------------------------------------------------
# Template / wikicode cleaning helpers
# ---------------------------------------------------------------------------


def _strip_refs(text: str) -> str:
    """Remove <ref>…</ref> blocks from *text*."""
    return re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)


def _clean_wikilinks(text: str) -> str:
    """Convert ``[[target|display]]`` / ``[[target]]`` to plain text."""
    return re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", text)


def _clean_definition(raw: str) -> str:
    """Return a readable plain-text string for a single definition line.

    Strategy: use mwparserfromhell to walk and simplify templates, then
    strip any remaining markup.  Falls back to regex stripping on error.
    """
    try:
        parsed = mwparserfromhell.parse(raw)
        # We iterate over a snapshot of templates to avoid mutation issues.
        for template in list(parsed.filter_templates()):
            name = str(template.name).strip().lower()
            params = list(template.params)

            def _pv(idx: int) -> str:
                return str(params[idx].value).strip() if idx < len(params) else ""

            # --- Labels / context markers ---
            if name in ("lb", "label", "context", "cx"):
                # {{lb|lang|label1|label2|…}}  →  [label1, label2]
                labels = [
                    str(p.value).strip()
                    for p in params[1:]
                    if str(p.value).strip() not in ("_", "-", ";", "")
                ]
                parsed.replace(template, f"[{', '.join(labels)}] " if labels else "")
            elif name == "ng":
                parsed.replace(template, _pv(0))
            elif name in ("defdate", "def-date"):
                parsed.replace(template, f"(dated: {_pv(0)})")
            elif name in ("taxfmt", "taxlink", "taxon"):
                parsed.replace(template, _pv(0))
            elif name in ("gloss", "gl"):
                parsed.replace(template, f"({_pv(0)})")
            elif name in ("q", "qual", "qualifier", "i", "italic"):
                parsed.replace(template, f"({_pv(0)})")
            elif name in ("m", "mention", "l", "link", "m+"):
                # {{m|lang|word|gloss}} → word (gloss)
                word = _pv(1)
                gloss = next(
                    (
                        str(p.value).strip()
                        for p in params
                        if str(p.name).strip().lower() in ("t", "gloss", "3")
                    ),
                    "",
                )
                replacement = word + (f" ({gloss})" if gloss else "")
                parsed.replace(template, replacement)
            elif name in ("only used in", "only-in"):
                if params:
                    parsed.replace(template, f"only used in {_pv(0)}")
                else:
                    parsed.replace(template, "")
            elif name in ("non-gloss definition", "n-g", "non gloss definition"):
                parsed.replace(template, _pv(0))
            elif name in ("sup", "superscript", "sub"):
                parsed.replace(template, "")
            elif name.startswith("rq:") or name.startswith("quote"):
                parsed.replace(template, "")
            elif name in ("ref", "r"):
                parsed.replace(template, "")
            else:
                # Generic fallback: use the first positional unnamed param, if any.
                unnamed = [
                    str(p.value).strip()
                    for p in params
                    if not str(p.name).strip().isdigit()
                    or str(p.name).strip() == "1"
                ]
                replacement = unnamed[0] if unnamed else ""
                # But don't replace with something that looks like a template param.
                if "|" in replacement or "=" in replacement:
                    replacement = ""
                parsed.replace(template, replacement)

        text = str(parsed)
        text = _clean_wikilinks(text)
        text = _strip_refs(text)
        # Remove leftover <tag> elements.
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    except Exception as exc:  # noqa: BLE001
        logger.debug("clean_definition fallback for %r: %s", raw[:60], exc)
        text = re.sub(r"\{\{[^}]+\}\}", "", raw)
        text = _clean_wikilinks(text)
        return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Definition extraction
# ---------------------------------------------------------------------------


def _extract_definitions(pos_content: str) -> List[str]:
    """Return plain-text numbered definitions from a POS section.

    Only first-level ``#`` lines are captured (not ``##`` examples).
    """
    definitions: List[str] = []
    for line in pos_content.split("\n"):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        # Count leading # characters.
        depth = len(line) - len(line.lstrip("#"))
        if depth != 1:
            continue  # Skip sub-definitions / examples
        raw = stripped[1:].strip()
        cleaned = _clean_definition(raw)
        if cleaned:
            definitions.append(cleaned)
    return definitions


# ---------------------------------------------------------------------------
# Derived / related / descendant term extraction
# ---------------------------------------------------------------------------


def _extract_linked_terms(section_text: str) -> List[str]:
    """Return all linked words from a section (derived / related / descendants).

    Handles:
      * {{l|lang|word}} / {{link|…}}
      * {{desc|lang|word}} / {{desctree|…}}
      * {{col|lang|word1|word2|…}}
      * [[word]] / [[word|display]]
    """
    terms: List[str] = []

    try:
        parsed = mwparserfromhell.parse(section_text)

        for template in parsed.filter_templates():
            name = str(template.name).strip().lower()
            params = list(template.params)

            def _pv(idx: int) -> str:
                return str(params[idx].value).strip() if idx < len(params) else ""

            if name in LINK_TEMPLATES:
                word = _pv(1)
                if word:
                    terms.append(word)
            elif name in DESCENDANT_TEMPLATES:
                word = _pv(1)
                if word:
                    terms.append(word)
            elif name in COLUMN_TEMPLATES:
                # {{col|lang|word1|word2|…}} – first param is language code
                for p in params[1:]:
                    w = str(p.value).strip()
                    if w and "=" not in w:
                        terms.append(w)

        for link in parsed.filter_wikilinks():
            target = str(link.title).strip()
            if target and not target.startswith(
                ("Category:", "File:", "Image:", "Wikipedia:", "Wiktionary:")
            ):
                terms.append(target)

    except Exception as exc:  # noqa: BLE001
        logger.debug("extract_linked_terms fallback: %s", exc)
        # Regex fallback
        terms += re.findall(r"\{\{l\|[^|]+\|([^|}\s]+)", section_text)
        terms += re.findall(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", section_text)

    # Deduplicate while preserving order; skip empty / punctuation-only strings.
    seen: set[str] = set()
    result: List[str] = []
    for t in terms:
        t = t.strip()
        if t and t not in seen and re.search(r"\w", t):
            seen.add(t)
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# Etymology parsing
# ---------------------------------------------------------------------------


def _parse_etymology_number(title: str) -> int:
    """Extract the number from 'Etymology 1', 'Etymology 2', etc.

    Returns 1 if no number is found.
    """
    m = re.search(r"\d+", title)
    return int(m.group()) if m else 1


def _clean_etymology_text(raw: str) -> str:
    """Return readable plain text for an etymology block."""
    text = _strip_refs(raw)
    try:
        parsed = mwparserfromhell.parse(text)
        # Strip the heading line itself if it crept in.
        for heading in list(parsed.filter_headings()):
            parsed.replace(heading, "")
        text = parsed.strip_code()
    except Exception:  # noqa: BLE001
        text = re.sub(r"\{\{[^}]+\}\}", "", text)
    text = _clean_wikilinks(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_parent_words(etymology_text: str) -> List[str]:
    """Return parent-word strings extracted from etymology template calls.

    Only ``{{inh}}``, ``{{bor}}``, ``{{der}}``, ``{{root}}`` and ``{{affix}}``
    are treated as *parent* relationships.  Cognates (``{{cog}}``) are
    intentionally excluded.

    Each result has the form ``"word (lang-code)"``.
    """
    if not etymology_text:
        return []

    parent_words: List[str] = []

    try:
        parsed = mwparserfromhell.parse(etymology_text)
        for template in parsed.filter_templates():
            name = str(template.name).strip().lower()
            if name not in INHERITANCE_TEMPLATES:
                continue
            params = list(template.params)
            if len(params) < 2:
                continue
            # Positional param layout: |lang1|lang2|word|…
            # params[0] = lang1 (recipient), params[1] = lang2 (source),
            # params[2] = word form in source language.
            lang = str(params[1].value).strip()
            word_val = str(params[2].value).strip() if len(params) > 2 else ""

            # Skip empty or placeholder values like "-".
            if word_val and word_val not in ("-", ""):
                parent_words.append(f"{word_val} ({lang})")

    except Exception as exc:  # noqa: BLE001
        logger.debug("extract_parent_words error: %s", exc)

    # Deduplicate.
    seen: set[str] = set()
    result = []
    for pw in parent_words:
        if pw not in seen:
            seen.add(pw)
            result.append(pw)
    return result


# ---------------------------------------------------------------------------
# Record assembly
# ---------------------------------------------------------------------------


def _build_record(
    word: str,
    language: str,
    pos: str,
    etymology_index: int,
    etymology_text: str,
    parent_words: List[str],
    pos_content: str,
    derived_level: int,
) -> Dict:
    """Assemble a single output record from extracted components."""
    sections = _split_sections(pos_content)

    definitions = _extract_definitions(pos_content)

    derived_terms: List[str] = []
    descendants: List[str] = []
    related_terms: List[str] = []

    for lvl, title, content in sections:
        if lvl < derived_level:
            continue
        t_lower = title.lower()
        if t_lower in ("derived terms", "derived"):
            derived_terms = _extract_linked_terms(content)
        elif t_lower in ("descendants",):
            descendants = _extract_linked_terms(content)
        elif t_lower in ("related terms", "related"):
            related_terms = _extract_linked_terms(content)

    return {
        "word": word,
        "language": language,
        "part_of_speech": pos,
        "etymology_index": etymology_index,
        "etymology_text": etymology_text,
        "parent_words": parent_words,
        "definitions": definitions,
        "derived_terms": derived_terms,
        "descendants": descendants,
        "related_terms": related_terms,
    }


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


class WiktionaryParser:
    """Parse the wikitext of a Wiktionary page into structured records."""

    def parse(self, wikitext: str, title: str, language: str) -> List[Dict]:
        """Return a list of records for *title* in *language*.

        Each record covers one (etymology × POS) combination.  Returns an
        empty list if no relevant content is found.
        """
        records: List[Dict] = []

        # ---------------------------------------------------------------
        # 1. Extract the language section
        # ---------------------------------------------------------------
        lang_section = _extract_language_section(wikitext, language)
        if not lang_section:
            logger.debug("No %r section in %r", language, title)
            return records

        sections = _split_sections(lang_section)

        # ---------------------------------------------------------------
        # 2. Decide layout: numbered etymologies or flat POS?
        # ---------------------------------------------------------------
        etym_sections = _find_sections(sections, level=3, title_prefix="etymology ")
        # Also catch a single "Etymology 1" with no number 2, and
        # plain "Etymology" (no number) treated separately below.
        numbered_etyms = _find_sections(sections, level=3, title_prefix="etymology ")

        if numbered_etyms:
            # --- Layout A: Etymology 1 / 2 / … at L3, POS at L4 ---
            records = self._parse_layout_a(title, language, sections, numbered_etyms)
        else:
            # --- Layout B: optional single Etymology at L3, POS at L3 ---
            records = self._parse_layout_b(title, language, sections)

        if not records:
            logger.debug("No records extracted for %r (%s)", title, language)

        return records

    # ------------------------------------------------------------------
    # Layout A helpers
    # ------------------------------------------------------------------

    def _parse_layout_a(
        self,
        title: str,
        language: str,
        sections: List[Tuple[int, str, str]],
        etym_sections: List[Tuple[str, str]],
    ) -> List[Dict]:
        records: List[Dict] = []

        for etym_title, etym_content in etym_sections:
            etym_num = _parse_etymology_number(etym_title)
            # The etymology text is the preamble of the section before any
            # subsection heading.
            etym_raw = self._section_preamble(etym_content)
            etym_text = _clean_etymology_text(etym_raw)
            parent_words = _extract_parent_words(etym_raw)

            # POS sections are at L4 within the etymology content.
            inner = _split_sections(etym_content)
            pos_sections = [
                (t, c)
                for lvl, t, c in inner
                if lvl == 4 and t.lower() in POS_NAMES
            ]

            if not pos_sections:
                # Some entries have etymology + no explicit POS header.
                # Attempt to read definitions from the preamble.
                definitions = _extract_definitions(etym_raw)
                if definitions:
                    records.append(
                        {
                            "word": title,
                            "language": language,
                            "part_of_speech": "",
                            "etymology_index": etym_num,
                            "etymology_text": etym_text,
                            "parent_words": parent_words,
                            "definitions": definitions,
                            "derived_terms": [],
                            "descendants": [],
                            "related_terms": [],
                        }
                    )
                continue

            for pos_title, pos_content in pos_sections:
                record = _build_record(
                    word=title,
                    language=language,
                    pos=pos_title,
                    etymology_index=etym_num,
                    etymology_text=etym_text,
                    parent_words=parent_words,
                    pos_content=pos_content,
                    derived_level=5,
                )
                records.append(record)

        return records

    # ------------------------------------------------------------------
    # Layout B helpers
    # ------------------------------------------------------------------

    def _parse_layout_b(
        self,
        title: str,
        language: str,
        sections: List[Tuple[int, str, str]],
    ) -> List[Dict]:
        records: List[Dict] = []

        # Find optional single etymology section at L3.
        etym_sections_b = _find_sections(sections, level=3, title_prefix="etymology", exact=True)
        etym_raw = etym_sections_b[0][1] if etym_sections_b else ""
        etym_text = _clean_etymology_text(etym_raw) if etym_raw else ""
        parent_words = _extract_parent_words(etym_raw) if etym_raw else []

        # POS sections at L3.
        pos_sections = [
            (t, c)
            for lvl, t, c in sections
            if lvl == 3 and t.lower() in POS_NAMES
        ]

        for pos_title, pos_content in pos_sections:
            record = _build_record(
                word=title,
                language=language,
                pos=pos_title,
                etymology_index=1,
                etymology_text=etym_text,
                parent_words=parent_words,
                pos_content=pos_content,
                derived_level=4,
            )
            records.append(record)

        return records

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _section_preamble(section_content: str) -> str:
        """Return the text of *section_content* before the first sub-heading."""
        m = _HEADING_RE.search(section_content)
        return section_content[: m.start()] if m else section_content
