# wiktionary3 – Structured Linguistic Dataset Builder

Scrapes and parses **Coptic**, **Egyptian (Hieroglyphic)**, and **Demotic
Egyptian** entries from English Wiktionary, producing structured JSON records
suitable for linguistic analysis and NLP.

Data from en.wiktionary.org is licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

---

## Output record schema

Each output record covers one *(word × etymology × part-of-speech)*
combination:

```json
{
  "word":            "ꜣ",
  "language":        "Egyptian",
  "part_of_speech":  "Noun",
  "etymology_index": 1,
  "etymology_text":  "Possibly from *ʔay- (Afro-Asiatic)",
  "parent_words":    ["*ʔay- (afa-pro)"],
  "definitions":     ["the Egyptian vulture", "a bird in general"],
  "derived_terms":   ["ꜣbd", "ꜣmw"],
  "descendants":     ["ⲁ"],
  "related_terms":   []
}
```

Records are written in **JSON Lines** format (`output/records.jsonl`): one
JSON object per line, UTF-8, no BOM.

---

## File layout

```
wiktionary3/
├── main.py           # CLI entry point
├── scraper.py        # Wiktionary MediaWiki API fetcher
├── parser.py         # Wikitext → structured records
├── crawler.py        # BFS crawler with visited-set deduplication
├── test_parser.py    # Unit tests (65 tests)
└── requirements.txt  # Python dependencies
```

**Output** (created at runtime, default `output/`):

| File | Description |
|------|-------------|
| `records.jsonl` | All extracted records, one JSON object per line |
| `visited.json`  | Sorted list of processed page titles (for resuming) |
| `anomalies.log` | Warnings / parse errors logged during the run |

---

## Installation

```bash
pip install -r requirements.txt
```

Requires Python ≥ 3.10.

---

## Usage

### Scrape all three languages (default)

```bash
python main.py
```

### Scrape one language only

```bash
python main.py --languages Coptic
python main.py --languages Egyptian
python main.py --languages Demotic
```

### Quick test run (200 pages)

```bash
python main.py --max-pages 200 --output-dir output_test
```

### Resume a previous run

Already-visited pages are skipped automatically via `output/visited.json`.
Just run the same command again:

```bash
python main.py --output-dir output
```

### Expand sub-categories

```bash
python main.py --expand-subcategories
```

### Parse a pre-fetched JSONL file (offline mode)

Supply a `.jsonl` file where each line is `{"title": "…", "language": "…",
"wikitext": "…"}`:

```bash
python main.py --parse-only raw_pages.jsonl --output-dir output
```

### All options

```
usage: python main.py [-h] [--languages LANG [LANG ...]]
                      [--output-dir DIR] [--max-pages N]
                      [--expand-subcategories] [--rate-limit SEC]
                      [--parse-only JSONL_FILE] [--verbose]

optional arguments:
  --languages LANG …      Coptic Egyptian Demotic (default: all three)
  --output-dir DIR        Output directory (default: output/)
  --max-pages N           Stop after N pages
  --expand-subcategories  Also crawl sub-categories one level deep
  --rate-limit SEC        Seconds between API calls (min 1.0, default 1.2)
  --parse-only JSONL_FILE Skip crawling; parse pre-fetched wikitext
  --verbose               Enable DEBUG logging
```

---

## Architecture

### Phase 1 – Learning Wiktionary structure (`parser.py`)

The parser was designed after analysing 50–100 sample pages across all three
target languages.  Key observations:

| Pattern | Description |
|---------|-------------|
| **Layout A** | Multiple etymologies at L3 (`===Etymology 1===`), POS at L4 (`====Noun====`), derived/descendants at L5 |
| **Layout B** | Single optional `===Etymology===` at L3, POS directly at L3, derived terms at L4 |
| Mixed | Some pages use L3 for POS even when a numbered etymology exists |

`_split_sections()` extracts `(level, title, content)` tuples where *content*
runs until the next heading at the same or higher level—this correctly captures
all sub-sections as part of their parent.

### Phase 2 – Data extraction (`parser.py`)

| Component | Implementation |
|-----------|---------------|
| Language section | Regex-based L2 heading match; handles "Demotic" ↔ "Demotic Egyptian" alias |
| Etymology text | `_clean_etymology_text()` strips refs, headings, and templates |
| Parent words | `_extract_parent_words()` reads `{{inh}}`, `{{bor}}`, `{{der}}`, `{{root}}` templates; excludes cognates (`{{cog}}`) |
| Definitions | `_extract_definitions()` collects depth-1 `#` lines, cleans labels/dates/links |
| Derived / related | `_extract_linked_terms()` handles `{{l}}`, `{{desc}}`, `{{col}}`, `[[wikilinks]]` |

### Phase 3 – Crawling (`crawler.py`)

1. Seeds the BFS queue from category pages (`Coptic lemmas`, `Egyptian lemmas`,
   `Demotic lemmas`, and sub-categories for each).
2. Parses each fetched page; appends records to `records.jsonl`.
3. Extracts words from `derived_terms`, `descendants`, and `related_terms` and
   adds them to the queue.
4. Deduplicates via a persistent `visited.json` set—safe to interrupt and
   resume.

---

## Running the tests

```bash
python -m pytest test_parser.py -v
```

All 65 tests cover:
* Section splitting
* Language-section extraction (including aliases)
* Definition extraction (templates, sub-definitions)
* Linked-term extraction (`{{l}}`, `{{desc}}`, `{{col}}`, wikilinks)
* Parent-word extraction from etymology templates
* Definition cleaning (labels, dates, taxa, wikilinks)
* Etymology number parsing
* Hieroglyph extraction (`head=` params, `{{egy-hieroforms|…}}` positional params)
* Full end-to-end parser on Egyptian (multi-etymology), Coptic, and Demotic
  fixture pages
* Record schema completeness
