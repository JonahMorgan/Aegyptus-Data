# Unified Dictionary

Merges every source folder into one Egyptian → Demotic → Coptic etymological graph keyed on TLA lemma IDs.
Schema, ID scheme and licensing: [SCHEMA.md](SCHEMA.md).

```
python Unified/build.py            # -> Unified/output/{entries,relations}.jsonl + build_report.json  (~15 s)
python Unified/build.py --public   # same, minus glosses from copyrighted sources -> Unified/output/public/
```

Per-source dictionaries (same schema, before any cross-source matching):

```
python Unified/export_sources.py   # -> Unified/output/sources/<source>/{entries,relations}.jsonl + summary.json
```

## Analysis

Run after `build.py`, in this order (each writes `.md` + `.json` to `Unified/output/reports/`):

```
python Unified/analysis/compare.py             # coverage, attach rates, gloss + etymology agreement between sources
python Unified/analysis/correspondence.py      # learned Egyptian→Demotic→Coptic sound correspondences
python Unified/analysis/etymology_scoring.py   # held-out accuracy, ORAEC-vs-Wiktionary disputes, low-scoring links
python Unified/analysis/suggest.py             # candidate etymologies for Coptic words no source etymologizes
```

The correspondence model is a stochastic edit distance trained by hard EM on ORAEC's ID-linked pairs, seeded
from letter co-occurrence (no hand-written phonetic values). `etymology_scoring.py` reports its held-out
accuracy; `suggest.py` reports how often it recovers hidden known etymologies, so the suggestion list can be
read with a known hit rate. Suggestions are never written into the dictionary.

## Pipeline

| Stage | Reads | Contributes |
|---|---|---|
| `coptic` | BBAW Comprehensive Coptic Lexicon XML, Coptic Dictionary Online, ORAEC | Coptic backbone (forms by dialect, de/en/fr glosses, Crum/CED page refs), Greek loan sources, Coptic→Demotic→Egyptian links by TLA ID |
| `tla` | TLA corpus (Earlier Egyptian, Late Egyptian, Demotic) | Egyptian/Demotic lemma inventory; token counts, date range, POS per lemma ID |
| `wiktionary` | `Wiktionary/*_lemmas_parsed_mwp.json` | English glosses, alternative forms, descendant trees, Coptic/Demotic etymology templates, `{{R:egy:TLA}}` IDs |
| `dme` | `Dictionary of Middle Egyptian/middle_egyptian_entries.json` | English glosses, Gardiner sign codes |
| `ede` | `Etymological Dictionary of Egyptian/ede_lemmas.json` | Takács headwords, glosses, page refs |
| `match` | — | folds provisional `{lang}:{source}:{word}` entries onto TLA/BBAW entries (see `stages/match.py` for the tie-break rules) |

Each merged source records how it was matched in `sources.<name>.match` (`tla_ref`, `key`, `gloss`, `pos`, `neighbour`).
Entries the matcher could not resolve keep their provisional ID and list `candidates`.

## Regenerating source outputs

```
python "Dictionary of Middle Egyptian/pdfdict_parse.py"
python "Etymological Dictionary of Egyptian/parse_ede.py"
python "Coptic Etymological Dictionary/ced_index.py"        # needs Unified output
python "Coptic Etymological Dictionary/ocr_ced.py" --all     # deferred: Tesseract-based draft, never run
```

## Measured quality

Current figures are regenerated in `output/reports/` on every run; as of the last build:

- Coptic etymologies: Wiktionary (via the matcher) names the same ancestor as ORAEC for 82% of shared words, 92% counting
  spelling variants with the same strong consonants (`comparison.md`). ORAEC and Coptic Dictionary Online agree on all
  but one, because both derive from TLA.
- Sound-correspondence model: true links beat random same-stage lemmas with AUC 0.96–0.99 (`etymology_scoring.md`).
- Suggestions: 65% top-1 / 88% top-3 on hidden ORAEC etymologies whose ancestor passes the gloss filter; only ~1/3 do,
  because most TLA Egyptian lemmas have no English gloss (`suggestions.md`).

## Known gaps

- TLA attestation comes from the "premium" sentence subsets on Hugging Face (~30k sentences); lemmas absent there have no `attestation`.
- Coptic Dictionary Online examples are empty in the parsed data; the raw HTML is no longer on disk.
- EDE Afroasiatic comparanda are kept as text in `ede_lemmas.json`, not yet split into `cognate` relations.
- Černý (CED) OCR is deferred. `ced_page_index.json` (page → expected lemma IDs + Crum refs) is ready for whatever OCR engine is chosen; `ocr_ced.py` is an unrun Tesseract draft whose Crum-anchor alignment can be reused.
- Greek has two unreconciled ID spaces: `grc:<DDGLC id>` (BBAW) and `grc:wikt:<word>` (Wiktionary).
- Wiktionary's descendant trees bring in later loans (Greek, Latin, Arabic, English...) as `borrowed_from` entries.
- BBAW lists some lemmas twice (e.g. ϭⲱⲛⲧ C7788/C7789); an etymology on one is not propagated to the other.
- Most TLA Egyptian lemmas carry no gloss here, which limits gloss-based matching and suggestions.
