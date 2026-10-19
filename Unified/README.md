# Unified Dictionary

Merges every source folder into one Egyptian → Demotic → Coptic etymological graph keyed on TLA lemma IDs.
Schema, ID scheme and licensing: [SCHEMA.md](SCHEMA.md).

```
python Unified/build.py            # -> Unified/output/{entries,relations}.jsonl + build_report.json  (~15 s)
python Unified/build.py --public   # same, minus glosses from copyrighted sources -> Unified/output/public/
```

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

Where ORAEC (by TLA ID) and Wiktionary (via the matcher) both give a Coptic word's ancestor, Wiktionary's
resolved parent lies on ORAEC's chain for ~77% (330 / 426). ~8% pick a same-spelling homograph with a different
TLA ID and ~15% differ outright (a mix of real scholarly disagreement and matcher error). Treat single-source
`descends_from` edges from Wiktionary accordingly; `sources` on each relation shows who asserts it.

## Known gaps

- TLA attestation comes from the "premium" sentence subsets on Hugging Face (~30k sentences); lemmas absent there have no `attestation`.
- Coptic Dictionary Online examples are empty in the parsed data; the raw HTML is no longer on disk.
- EDE Afroasiatic comparanda are kept as text in `ede_lemmas.json`, not yet split into `cognate` relations.
- Černý (CED) OCR is deferred. `ced_page_index.json` (page → expected lemma IDs + Crum refs) is ready for whatever OCR engine is chosen; `ocr_ced.py` is an unrun Tesseract draft whose Crum-anchor alignment can be reused.
- Greek has two unreconciled ID spaces: `grc:<DDGLC id>` (BBAW) and `grc:wikt:<word>` (Wiktionary).
- Wiktionary's descendant trees bring in later loans (Greek, Latin, Arabic, English...) as `borrowed_from` entries.
