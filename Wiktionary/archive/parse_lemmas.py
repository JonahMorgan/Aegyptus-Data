#!/usr/bin/env python3
"""
Lemma Parser - Extracts and saves parsed lemma data from Wiktionary JSON files.

This script loads the three lemma JSON files (Egyptian, Demotic, Coptic) and saves
them to new files with additional parsing applied where needed. The parsing algorithms
are extracted from build_lemma_networks_v2.py.

Usage:
    python parse_lemmas.py

Output:
    - egyptian_lemmas_parsed_new.json
    - demotic_lemmas_parsed_new.json
    - coptic_lemmas_parsed_new.json
"""

import json
import re
import sys
import os

class LemmaParser:
    """Parse lemma data from Wiktionary JSON files"""

    def __init__(self):
        pass

    def extract_etymology_mentions(self, etymology_text):
        """
        Extract additional etymological mentions from etymology text.
        Parses {{m}}, {{l}}, {{inh}}, {{bor}}, {{der}} templates that may not be in etymology_ancestors.
        Returns list of dicts: [{'language': 'egx-dem', 'form': 'ḫyḫ', 'gloss': 'dust', 'type': 'm'}, ...]
        """
        mentions = []
        if not etymology_text:
            return mentions

        # Regex to match {{template|lang|term||gloss}} patterns
        # Matches: {{m|egx-dem|ḫyḫ||dust}}, {{inh|cop|egx-dem|šyḫ}}, {{l|cop|ϣⲱϣ||scatter}}
        pattern = r'\{\{(m|l|inh|bor|der)\|([^|}\n]+?)\|([^|}\n]+?)(?:\|([^|}\n]*?))?(?:\|([^}]*?))?\}\}'

        for match in re.finditer(pattern, etymology_text):
            template_type = match.group(1)  # m, l, inh, bor, der
            lang = match.group(2).strip()
            term = match.group(3).strip()
            param3 = match.group(4).strip() if match.group(4) else ''
            param4 = match.group(5).strip() if match.group(5) else ''

            # For {{inh|cop|egx-dem|šyḫ}}, lang is param2, term is param3
            if template_type in ['inh', 'bor', 'der']:
                # Format: {{type|target_lang|source_lang|term||gloss}}
                source_lang = term if '|' not in term else term.split('|')[0]
                actual_term = param3 if param3 else ''
                gloss = param4 if param4 else ''
                # Remove leading | from gloss
                if gloss.startswith('|'):
                    gloss = gloss[1:]
            else:
                # Format: {{m|lang|term||gloss}} or {{l|lang|term||gloss}}
                source_lang = lang
                actual_term = term
                # Gloss is after ||, check if param3 is empty and param4 has content
                gloss = param4 if param3 == '' and param4 else param3

            if actual_term and source_lang:
                mentions.append({
                    'language': source_lang,
                    'form': actual_term,
                    'gloss': gloss,
                    'type': template_type
                })

        return mentions

    def parse_etymology_chain(self, etymology_text):
        """
        Parse etymology text to extract chain structure from "from X, from Y, from Z" patterns.
        Returns list of chain links in order from oldest to newest: [oldest, ..., newest]
        Each link: {'language': 'egy', 'form': 'rwꜣbw', 'gloss': '', 'type': 'm'}
        """
        if not etymology_text:
            return []

        # Extract the main etymology section (after "===Etymology===" or "From")
        # Look for patterns like "From {{inh|...|X}}, from {{inh|...|Y}}, from {{m|...|Z}}"

        chain = []

        # Split on "from" to find chain segments
        # Match: "from {{template...}}" or "from earlier {{template...}}" patterns
        from_pattern = r'[Ff]rom\s+(?:earlier\s+)?(\{\{[^}]+\}\}(?:,?\s*\{\{[^}]+\}\})*)'

        matches = list(re.finditer(from_pattern, etymology_text))

        for match in matches:
            template_text = match.group(1)

            # Extract all templates in this "from" clause
            template_pattern = r'\{\{(m|l|inh|bor|der)\|([^}]+)\}\}'
            for tmpl_match in re.finditer(template_pattern, template_text):
                template_type = tmpl_match.group(1)
                params = tmpl_match.group(2)

                # Parse parameters
                parts = [p.strip() for p in params.split('|')]

                if template_type in ['inh', 'bor', 'der']:
                    # Format: target_lang|source_lang|term||gloss
                    if len(parts) >= 3:
                        source_lang = parts[1]
                        term = parts[2]
                        gloss = parts[3] if len(parts) > 3 else ''
                        if gloss.startswith('|'):
                            gloss = gloss[1:]

                        chain.append({
                            'language': source_lang,
                            'form': term,
                            'gloss': gloss,
                            'type': template_type,
                            'position': match.start()  # Track position for ordering
                        })
                else:
                    # Format: lang|term||gloss
                    if len(parts) >= 2:
                        source_lang = parts[0]
                        term = parts[1]
                        gloss = ''
                        # Check for gloss after ||
                        for i in range(2, len(parts)):
                            if parts[i]:
                                gloss = parts[i]
                                break
                        # Strip leading | from gloss
                        if gloss.startswith('|'):
                            gloss = gloss[1:]

                        chain.append({
                            'language': source_lang,
                            'form': term,
                            'gloss': gloss,
                            'type': template_type,
                            'position': match.start()
                        })

        # Sort by position (chronological order in text = oldest to newest)
        # Reverse to get oldest first
        chain.sort(key=lambda x: x['position'], reverse=True)

        # Remove position field
        for item in chain:
            del item['position']

        return chain

    def extract_hieroglyphs_from_params(self, params):
        """Extract hieroglyphs from template parameters (e.g., head parameter)"""
        if not params:
            return None

        # If params is a string, parse it
        if isinstance(params, str):
            # Look for head=<hiero>...</hiero> or head=hieroglyphs pattern
            match = re.search(r'head=<hiero>([^<]+)</hiero>', params)
            if match:
                return match.group(1)

            # Look for head=something (without hiero tags)
            match = re.search(r'head=([^|]+)', params)
            if match:
                return match.group(1).strip()

        # If params is a dict
        elif isinstance(params, dict):
            head = params.get('head', '')
            if head:
                # Extract hieroglyphs from <hiero> tags
                match = re.search(r'<hiero>([^<]+)</hiero>', head)
                if match:
                    return match.group(1)
                # If no tags, the whole head might be hieroglyphs
                return head

        return None

    def parse_egyptian_lemmas(self, raw_data):
        """Parse Egyptian lemma data - apply any additional parsing if needed"""
        # For now, just return the data as-is since it's already parsed
        # But we can add etymology parsing here if needed
        parsed = {}
        for lemma_form, entry in raw_data.items():
            parsed_entry = entry.copy()

            # Add etymology mentions if not present
            for etym in parsed_entry.get('etymologies', []):
                etym_text = etym.get('etymology_text', '')
                if etym_text and 'etymology_mentions' not in etym:
                    etym['etymology_mentions'] = self.extract_etymology_mentions(etym_text)
                if etym_text and 'etymology_chain' not in etym:
                    etym['etymology_chain'] = self.parse_etymology_chain(etym_text)

            parsed[lemma_form] = parsed_entry

        return parsed

    def parse_demotic_lemmas(self, raw_data):
        """Parse Demotic lemma data"""
        # Similar to Egyptian, add parsing if needed
        parsed = {}
        for lemma_form, entry in raw_data.items():
            parsed_entry = entry.copy()

            # Add etymology mentions
            for etym in parsed_entry.get('etymologies', []):
                etym_text = etym.get('etymology_text', '')
                if etym_text and 'etymology_mentions' not in etym:
                    etym['etymology_mentions'] = self.extract_etymology_mentions(etym_text)
                if etym_text and 'etymology_chain' not in etym:
                    etym['etymology_chain'] = self.parse_etymology_chain(etym_text)

            parsed[lemma_form] = parsed_entry

        return parsed

    def parse_coptic_lemmas(self, raw_data):
        """Parse Coptic lemma data"""
        # Similar to others
        parsed = {}
        for lemma_form, entry in raw_data.items():
            parsed_entry = entry.copy()

            # Add etymology mentions
            for etym in parsed_entry.get('etymologies', []):
                etym_text = etym.get('etymology_text', '')
                if etym_text and 'etymology_mentions' not in etym:
                    etym['etymology_mentions'] = self.extract_etymology_mentions(etym_text)
                if etym_text and 'etymology_chain' not in etym:
                    etym['etymology_chain'] = self.parse_etymology_chain(etym_text)

            parsed[lemma_form] = parsed_entry

        return parsed

def main():
    print("Lemma Parser - Parsing Wiktionary lemma data")
    print("=" * 50)

    parser = LemmaParser()

    # Load raw lemma data (assuming these are the input files)
    input_files = {
        'egyptian': 'egyptian_lemmas.json',
        'demotic': 'demotic_lemmas.json',
        'coptic': 'coptic_lemmas.json'
    }

    output_files = {
        'egyptian': 'egyptian_lemmas_parsed_new.json',
        'demotic': 'demotic_lemmas_parsed_new.json',
        'coptic': 'coptic_lemmas_parsed_new.json'
    }

    for lang, input_file in input_files.items():
        if not os.path.exists(input_file):
            print(f"Warning: {input_file} not found, skipping {lang}")
            continue

        print(f"Loading {lang} data from {input_file}...")
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)

        print(f"Parsing {lang} data ({len(raw_data)} entries)...")

        if lang == 'egyptian':
            parsed_data = parser.parse_egyptian_lemmas(raw_data)
        elif lang == 'demotic':
            parsed_data = parser.parse_demotic_lemmas(raw_data)
        elif lang == 'coptic':
            parsed_data = parser.parse_coptic_lemmas(raw_data)

        output_file = output_files[lang]
        print(f"Saving parsed {lang} data to {output_file}...")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(parsed_data, f, ensure_ascii=False, indent=2)

        print(f"Saved {len(parsed_data)} {lang} entries to {output_file}")

    print("\nParsing complete!")
    print("New parsed files created:")
    for lang, file in output_files.items():
        print(f"  - {file}")

if __name__ == '__main__':
    main()