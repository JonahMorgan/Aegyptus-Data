"""
main.py – CLI entry point for the wiktionary3 scraper/parser pipeline.

Usage examples
--------------
# Scrape all three target languages (default)
python main.py

# Scrape Coptic only
python main.py --languages Coptic

# Limit to 200 pages (good for testing)
python main.py --max-pages 200 --output-dir output_test

# Resume a previous run (already-visited pages are skipped automatically)
python main.py --output-dir output
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging setup (must come before importing project modules so that the
# anomaly file handler added by the Crawler is layered on top).
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("wiktionary3")

# ---------------------------------------------------------------------------
# Parse args before importing heavy modules to keep --help fast
# ---------------------------------------------------------------------------

VALID_LANGUAGES = ["Coptic", "Egyptian", "Demotic"]


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python main.py",
        description=(
            "Scrape and parse Coptic / Egyptian (Hieroglyphic) / Demotic "
            "entries from English Wiktionary and save structured JSON records."
        ),
    )
    p.add_argument(
        "--languages",
        nargs="+",
        choices=VALID_LANGUAGES,
        default=VALID_LANGUAGES,
        metavar="LANG",
        help=(
            f"Languages to scrape.  One or more of: {', '.join(VALID_LANGUAGES)}. "
            "(default: all three)"
        ),
    )
    p.add_argument(
        "--output-dir",
        default="output",
        metavar="DIR",
        help="Directory for output files (created if absent). (default: output/)",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help="Stop after processing N pages.  Omit for unlimited.",
    )
    p.add_argument(
        "--expand-subcategories",
        action="store_true",
        help="Also crawl one level of sub-categories under each seed category.",
    )
    p.add_argument(
        "--rate-limit",
        type=float,
        default=1.2,
        metavar="SEC",
        help=(
            "Seconds to pause between API calls.  "
            "Must be ≥ 1.0 to respect Wiktionary's rate limits. (default: 1.2)"
        ),
    )
    p.add_argument(
        "--parse-only",
        metavar="JSONL_FILE",
        help=(
            "Skip crawling; instead read raw wikitext from JSONL_FILE "
            "(format: one JSON per line with keys 'title', 'language', 'wikitext') "
            "and parse them into records."
        ),
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.rate_limit < 1.0:
        logger.warning(
            "--rate-limit %s is below 1.0 s; clamping to 1.0 to avoid rate-limiting.",
            args.rate_limit,
        )
        args.rate_limit = 1.0

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Mode A: parse-only (read pre-fetched JSONL)
    # ------------------------------------------------------------------
    if args.parse_only:
        from parser import WiktionaryParser  # noqa: PLC0415

        parse_only_path = Path(args.parse_only)
        if not parse_only_path.exists():
            logger.error("File not found: %s", parse_only_path)
            return 1

        records_path = output_dir / "records.jsonl"
        p = WiktionaryParser()
        written = 0

        with (
            open(parse_only_path, encoding="utf-8") as in_fh,
            open(records_path, "w", encoding="utf-8") as out_fh,
        ):
            for lineno, line in enumerate(in_fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    title = entry["title"]
                    language = entry["language"]
                    wikitext = entry["wikitext"]
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Line %d skipped – bad format: %s", lineno, exc)
                    continue

                records = p.parse(wikitext, title, language)
                for rec in records:
                    out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    written += 1

        logger.info(
            "Parse-only mode complete.  %d records written to %s",
            written,
            records_path,
        )
        return 0

    # ------------------------------------------------------------------
    # Mode B: full crawl
    # ------------------------------------------------------------------
    from crawler import Crawler  # noqa: PLC0415

    logger.info(
        "Starting crawl for languages: %s | output: %s | max_pages: %s",
        ", ".join(args.languages),
        output_dir,
        args.max_pages or "unlimited",
    )

    crawler = Crawler(
        languages=args.languages,
        output_dir=output_dir,
        max_pages=args.max_pages,
        expand_subcategories=args.expand_subcategories,
        rate_limit=args.rate_limit,
    )
    crawler.crawl()

    # Print a brief summary.
    records_path = output_dir / "records.jsonl"
    if records_path.exists():
        with open(records_path, encoding="utf-8") as fh:
            n_records = sum(1 for ln in fh if ln.strip())
        logger.info("Total records in output file: %d", n_records)

    return 0


if __name__ == "__main__":
    sys.exit(main())
