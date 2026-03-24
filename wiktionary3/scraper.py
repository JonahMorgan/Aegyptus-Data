"""
scraper.py – Wiktionary API fetcher for the wiktionary3 pipeline.

Handles all HTTP interactions:
  * paginated category-member listing
  * wikitext retrieval with exponential-back-off retries
  * optional subcategory expansion

Data from en.wiktionary.org is licensed under CC BY-SA 4.0.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://en.wiktionary.org/w/api.php"

HEADERS = {
    "User-Agent": (
        "Aegyptus-Wiktionary-Scraper/3.0 "
        "(https://github.com/JonahMorgan/Aegyptus-Data; educational/research)"
    ),
    "Accept": "application/json",
}

# How long to pause between successive API calls (seconds).
DEFAULT_RATE_LIMIT = 1.0

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


class WikitionaryScraper:
    """Thin wrapper around the Wiktionary MediaWiki API."""

    def __init__(self, rate_limit: float = DEFAULT_RATE_LIMIT, retries: int = 4):
        self.rate_limit = rate_limit
        self.retries = retries
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    # ------------------------------------------------------------------
    # Category membership
    # ------------------------------------------------------------------

    def get_category_members(
        self,
        category: str,
        namespace: int = 0,
        limit: int = 500,
    ) -> List[str]:
        """Return all page titles that are members of *category*.

        Args:
            category: Category name **without** the ``Category:`` prefix.
            namespace: MediaWiki namespace (0 = main/article, 14 = category).
            limit: Items per API page (max 500 for bots, 50 for anonymous).

        Returns:
            Sorted list of unique page titles.
        """
        members: List[str] = []
        cmcontinue: Optional[str] = None

        while True:
            params: dict = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": f"Category:{category}",
                "cmnamespace": namespace,
                "cmlimit": limit,
                "format": "json",
            }
            if cmcontinue:
                params["cmcontinue"] = cmcontinue

            data = self._get(params, context=f"category:{category}")
            if data is None:
                break

            for m in data.get("query", {}).get("categorymembers", []):
                members.append(m["title"])

            if "continue" not in data:
                break
            cmcontinue = data["continue"]["cmcontinue"]
            time.sleep(self.rate_limit)

        logger.info("Category %r → %d members", category, len(members))
        return members

    def get_subcategories(self, category: str) -> List[str]:
        """Return sub-category names inside *category* (namespace 14)."""
        titles = self.get_category_members(category, namespace=14)
        # Strip the "Category:" prefix so callers can feed the result back in.
        return [t.removeprefix("Category:") for t in titles]

    # ------------------------------------------------------------------
    # Page content
    # ------------------------------------------------------------------

    def get_page_wikitext(self, title: str) -> Optional[str]:
        """Fetch the raw wikitext for *title*, returning ``None`` on failure."""
        params = {
            "action": "query",
            "titles": title,
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "formatversion": "2",
            "format": "json",
        }

        for attempt in range(self.retries):
            data = self._get(params, context=f"page:{title}")
            if data is None:
                wait = 2 ** attempt
                logger.warning(
                    "Attempt %d/%d failed for %r – waiting %ds",
                    attempt + 1,
                    self.retries,
                    title,
                    wait,
                )
                time.sleep(wait)
                continue

            pages = data.get("query", {}).get("pages", [])
            if not pages:
                logger.warning("No pages returned for %r", title)
                return None

            page = pages[0]
            if page.get("missing"):
                logger.debug("Page missing: %r", title)
                return None

            revisions = page.get("revisions", [])
            if not revisions:
                logger.warning("No revisions for %r", title)
                return None

            slot = revisions[0].get("slots", {}).get("main", {})
            content = slot.get("content")
            if content is None:
                logger.warning("No content slot for %r", title)
                return None

            return content

        logger.error("Gave up fetching %r after %d attempts", title, self.retries)
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get(self, params: dict, context: str = "") -> Optional[dict]:
        """Perform a single GET request and return parsed JSON, or ``None``."""
        try:
            response = self._session.get(API_BASE, params=params, timeout=15)
            response.raise_for_status()
            data: dict = response.json()
            if "error" in data:
                logger.error("API error [%s]: %s", context, data["error"])
                return None
            return data
        except requests.HTTPError as exc:
            logger.error("HTTP %s for %s: %s", exc.response.status_code, context, exc)
            return None
        except (requests.RequestException, ValueError) as exc:
            logger.error("Request error for %s: %s", context, exc)
            return None
        finally:
            time.sleep(self.rate_limit)
