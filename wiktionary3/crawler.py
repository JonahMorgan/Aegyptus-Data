"""
crawler.py – Category-seeded BFS crawler for the wiktionary3 pipeline.

Crawling strategy
-----------------
1.  Seed the queue from the canonical Wiktionary category pages for each
    target language (e.g. "Coptic lemmas", "Egyptian lemmas").
2.  Optionally expand sub-categories one level deep.
3.  For each queued page title, fetch wikitext, run the parser, and append
    any new records to the output file.
4.  Any words mentioned in derived_terms / descendants / related_terms are
    added to the queue so the crawler follows the lexical graph recursively.
5.  A persistent visited set (stored as JSON) prevents re-processing and
    infinite loops.
6.  All records are written as JSON Lines (one JSON object per line) for
    memory-efficient incremental output.

Anomalies (parse failures, missing sections, etc.) are logged separately.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set

from scraper import WikitionaryScraper
from parser import WiktionaryParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language → seed-category mapping
# ---------------------------------------------------------------------------

LANGUAGE_CATEGORIES: Dict[str, List[str]] = {
    "Coptic": [
        "Coptic lemmas",
        "Coptic nouns",
        "Coptic verbs",
        "Coptic adjectives",
        "Coptic pronouns",
        "Coptic prepositions",
        "Coptic particles",
        "Coptic conjunctions",
        "Coptic determiners",
        "Coptic numerals",
        "Coptic proper nouns",
    ],
    "Egyptian": [
        "Egyptian lemmas",
        "Egyptian nouns",
        "Egyptian verbs",
        "Egyptian adjectives",
        "Egyptian pronouns",
        "Egyptian prepositions",
        "Egyptian particles",
        "Egyptian conjunctions",
        "Egyptian numerals",
        "Egyptian proper nouns",
    ],
    "Demotic": [
        "Demotic lemmas",
        "Demotic nouns",
        "Demotic verbs",
        "Demotic adjectives",
        "Demotic pronouns",
        "Demotic particles",
    ],
    "Demotic Egyptian": [
        "Demotic lemmas",
    ],
}


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------


def _atomic_json_write(path: Path, obj) -> None:
    """Write *obj* to *path* atomically via a temp-file rename."""
    dir_ = path.parent
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, suffix=".tmp", dir=dir_
    ) as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        tmp_name = fh.name
    os.replace(tmp_name, path)


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


class Crawler:
    """BFS crawler that builds a structured linguistic dataset from Wiktionary."""

    def __init__(
        self,
        languages: List[str],
        output_dir: str | os.PathLike = "output",
        max_pages: Optional[int] = None,
        expand_subcategories: bool = False,
        rate_limit: float = 1.2,
    ) -> None:
        """
        Parameters
        ----------
        languages:
            Target languages, e.g. ``["Coptic", "Egyptian", "Demotic"]``.
        output_dir:
            Directory where output files are written.  Created if absent.
        max_pages:
            Hard cap on pages processed (useful for testing / partial runs).
            ``None`` means no cap.
        expand_subcategories:
            Whether to also fetch the members of sub-categories one level
            deep under each seed category.
        rate_limit:
            Seconds to wait between API requests (passed to the scraper).
        """
        self.languages = languages
        self.output_dir = Path(output_dir)
        self.max_pages = max_pages
        self.expand_subcategories = expand_subcategories

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._scraper = WikitionaryScraper(rate_limit=rate_limit)
        self._parser = WiktionaryParser()

        # Paths
        self._records_path = self.output_dir / "records.jsonl"
        self._visited_path = self.output_dir / "visited.json"
        self._anomalies_path = self.output_dir / "anomalies.log"

        # Anomaly logger
        fh = logging.FileHandler(self._anomalies_path, encoding="utf-8")
        fh.setLevel(logging.WARNING)
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logging.getLogger().addHandler(fh)

        # Load existing visited set for resumability.
        self._visited: Set[str] = self._load_visited()

        # Count records already written (approximate, for logging).
        # Avoid calling stat() twice by storing the result.
        self._records_written: int = 0
        if self._records_path.exists():
            file_size = self._records_path.stat().st_size
            if file_size:
                self._records_written = file_size // 200  # rough bytes-per-record estimate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def crawl(self) -> None:
        """Run the full crawl.  Saves results incrementally as it goes."""
        # Open the records file inside crawl() so the file handle is always
        # closed when this method exits – whether normally or via exception.
        with open(self._records_path, "a", encoding="utf-8") as records_fh:
            self._records_fh = records_fh
            self._run_crawl()
        self._records_fh = None

    def _run_crawl(self) -> None:
        """Internal crawl loop (called with records file already open)."""
        queue: List[str] = self._build_initial_queue()

        logger.info(
            "Starting crawl: %d seed pages, %d already visited",
            len(queue),
            len(self._visited),
        )

        pages_processed = 0

        while queue:
            title = queue.pop(0)

            if title in self._visited:
                continue
            if self.max_pages is not None and pages_processed >= self.max_pages:
                logger.info("Reached max_pages=%d – stopping.", self.max_pages)
                break

            self._visited.add(title)

            # Determine which language(s) to parse for this page.
            for language in self.languages:
                new_links = self._process_page(title, language)
                # Add newly discovered words to the queue.
                for link in new_links:
                    if link not in self._visited:
                        queue.append(link)

            pages_processed += 1

            if pages_processed % 50 == 0:
                logger.info(
                    "Progress: %d pages processed, %d visited, ~%d records written",
                    pages_processed,
                    len(self._visited),
                    self._records_written,
                )
                self._save_visited()

        self._save_visited()
        logger.info(
            "Crawl complete. %d pages processed, ~%d records written.",
            pages_processed,
            self._records_written,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_initial_queue(self) -> List[str]:
        """Collect page titles from all seed categories."""
        titles: List[str] = []
        seen: Set[str] = set()

        for language in self.languages:
            categories = LANGUAGE_CATEGORIES.get(language, [f"{language} lemmas"])

            for cat in categories:
                members = self._scraper.get_category_members(cat)
                for t in members:
                    if t not in seen and t not in self._visited:
                        seen.add(t)
                        titles.append(t)

                if self.expand_subcategories:
                    for subcat in self._scraper.get_subcategories(cat):
                        for t in self._scraper.get_category_members(subcat):
                            if t not in seen and t not in self._visited:
                                seen.add(t)
                                titles.append(t)

        logger.info("Initial queue: %d unique titles", len(titles))
        return titles

    def _process_page(self, title: str, language: str) -> List[str]:
        """Fetch, parse, and persist one page.  Returns newly found link titles."""
        logger.debug("Processing %r for language %r", title, language)

        wikitext = self._scraper.get_page_wikitext(title)
        if wikitext is None:
            logger.warning("Could not fetch wikitext for %r", title)
            return []

        try:
            records = self._parser.parse(wikitext, title, language)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Parse error for %r (%s): %s", title, language, exc)
            return []

        if not records:
            return []

        new_links: List[str] = []
        for record in records:
            self._write_record(record)
            # Collect words to follow.
            for field in ("derived_terms", "descendants", "related_terms"):
                for linked_word in record.get(field, []):
                    if linked_word and linked_word not in self._visited:
                        new_links.append(linked_word)

        return new_links

    def _write_record(self, record: Dict) -> None:
        """Append a single record to the JSON Lines output file."""
        self._records_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._records_fh.flush()
        self._records_written += 1

    def _save_visited(self) -> None:
        """Persist the visited set to disk."""
        _atomic_json_write(self._visited_path, sorted(self._visited))

    def _load_visited(self) -> Set[str]:
        """Load a previously saved visited set, returning an empty set if absent."""
        if self._visited_path.exists():
            try:
                with open(self._visited_path, encoding="utf-8") as fh:
                    return set(json.load(fh))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not load visited set: %s", exc)
        return set()
