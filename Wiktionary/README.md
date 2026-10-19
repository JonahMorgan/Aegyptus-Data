# Wiktionary Data Collection

This directory contains tools for collecting and parsing Egyptian language data from Wiktionary.

## Pipeline

`wiktionary_get.py` (fetch) → `parse_with_mwparserfromhell.py` → `*_lemmas_parsed_mwp.json` →
`build_lemma_networks_v2.py` → `lemma_networks_v2.json` → `visualize/`.
All outputs are UTF-8. Older builders and outputs are in `archive/`; scratch scripts and logs in `debug/` (gitignored).
The parsed files also feed `Unified/stages/wiktionary.py`.

## TODO

- [ ] Make a new network builder that ONLY cares about descends nodes and alternate forms
- [x] First, on the v2 of the lemma networks builder, add the functionality that alternate forms descend from each other based on the time frame mentioned, like in v1

## Recent Changes

### Temporal Evolution and Network Structure Fixes (v2)
**Date:** November 4, 2025

**1. Added temporal evolution functionality:**
- Added `get_period_rank()` method to chronologically rank Egyptian periods and dynasties
- Alternative forms with dates now create **EVOLVES** edges showing temporal evolution
- Forms from the same period create **VARIANT** edges (all connected to each other)
- Main lemma connects to earliest dated form as "first attestation"

**2. Separate chains for different form types:**
- Alternative forms are now grouped by type: base, plural, dual, feminine, godhood, determinative
- Each type creates its own temporal chain descending from the root node
- Plural forms (jꜥnw) and godhood variants now form separate evolutionary branches
- Uses **DERIVED** edge type for non-base forms (plural, godhood, etc.)

**3. Fixed descendant connections:**
- ALL Demotic/Coptic descendants now connect from the LATEST dated Egyptian form
- Removed redundant edges from earlier forms when later forms exist
- Removed direct Egyptian→Coptic edges when Egyptian→Demotic→Coptic path exists
- Cleanup removes ~817 redundant edges automatically

**4. Added Coptic dialectal variants:**
- Standalone Coptic networks now include alternative forms (dialectal variants)
- Variants are connected with VARIANT edges labeled by dialect (Sahidic, Bohairic, Fayyumic, etc.)
- Example: ⲣⲉⲥⲧⲉ now shows ⲣⲁⲥⲧⲉ (Sahidic), ⲣⲁⲥϯ (Bohairic), ⲗⲉⲥϯ (Fayyumic)

**5. Organizational:**
- Moved debug/test scripts to `debug/` folder (already in .gitignore)
- Test scripts: `test_temporal_evolution.py`, `verify_fixes.py`, `verify_cleanup.py`
