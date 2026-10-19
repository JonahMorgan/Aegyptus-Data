# Unified Egyptian Etymological Dictionary — Schema

The unified dictionary is two JSONL files in `Unified/output/`:

- `entries.jsonl` — one lemma per line
- `relations.jsonl` — one directed edge between two lemma IDs per line

`build.py` produces both by running the stages in `stages/` in order. Each stage
reads one source folder and merges into a shared in-memory `Store` (see `schema.py`).

## IDs

TLA lemma IDs are the hub. Every source that carries them is joined on them.

| Language | Canonical ID | Example | Where the ID comes from |
|---|---|---|---|
| Earlier/Late Egyptian | `egy:<n>` | `egy:41430` | TLA, ORAEC, CDO links |
| Demotic | `dem:d<n>` | `dem:d875` | TLA, ORAEC (stored without the `d`) |
| Coptic | `cop:C<n>` | `cop:C24` | BBAW/CDO (same `C####` IDs) |
| Greek (loan sources) | `grc:<n>` | `grc:3742` | DDGLC IDs in the BBAW Comprehensive XML |

Sources without TLA IDs (Wiktionary, DME, EDE) get provisional IDs until the
transliteration matcher attaches them to a canonical entry:

- `egy:wikt:<lemma>`, `dem:wikt:<lemma>`, `cop:wikt:<lemma>`
- `egy:dme:<translit>`
- `egy:ede:<headword>`

## Entry

```json
{
  "id": "cop:C24",
  "lang": "cop",
  "lemma": "ⲁⲉⲓⲕ",
  "key": "ⲁⲉⲓⲕ",
  "pos": "Subst.",
  "gender": "m.",
  "forms":  [{"form": "ⲁⲓⲕ", "dialect": "B", "source": "bbaw"}],
  "senses": [{"lang": "en", "gloss": "consecration", "source": "bbaw"}],
  "refs":   [{"work": "CED", "loc": "12", "source": "bbaw"}],
  "attestation": {"tokens": 12, "date_min": -1580, "date_max": 250, "source": "tla"},
  "sources": {"bbaw": {"id": "C24"}, "cdo": {"tla": "C24"}}
}
```

- `key` is the normalized match key (see `translit.py`); for Coptic it is the
  lemma with combining marks stripped.
- `forms`, `senses`, `refs` are append-only lists; each item records its `source`.
- `sources` maps source name → that source's native identifiers, so every
  fact can be traced back.
- Fields not known are omitted rather than set to null.

## Relation

```json
{"src": "cop:C24", "dst": "dem:d875", "type": "descends_from", "sources": ["oraec", "cdo"]}
```

| type | meaning |
|---|---|
| `descends_from` | `src` is the inherited later form of `dst` (Coptic → Demotic → Egyptian) |
| `borrowed_from` | `src` is a loan from `dst` (e.g. Coptic ← Greek) |
| `variant_of` | spelling / dialectal / dated alternative of the same lemma |
| `derived_from` | compound or derivation built on `dst` |
| `cognate` | non-descent comparison (e.g. Afroasiatic comparanda in EDE) |
| `see_also` | editorial cross-reference (`cf.`) |

The same (src, dst, type) triple is stored once; `sources` lists every source
asserting it, so agreement between sources is visible.

## Source licensing

| Source | License | Can ship in public build |
|---|---|---|
| TLA corpus, BBAW lexicon | CC BY-SA 4.0 | yes, with attribution |
| Wiktionary | CC BY-SA 4.0 | yes, with attribution |
| ORAEC | CC0 | yes |
| Coptic Dictionary Online | CC BY-SA 4.0 | yes, with attribution |
| Dictionary of Middle Egyptian (Dickson) | free to distribute, terms unverified | check before shipping |
| EDE (Takács), CED (Černý) | copyrighted | internal only; ship only IDs/refs |

`build.py --public` drops glosses from the copyrighted sources.
