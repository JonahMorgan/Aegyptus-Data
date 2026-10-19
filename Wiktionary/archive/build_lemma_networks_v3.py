"""
Lemma Network Builder V3 - Ego-centric approach with systematic section parsing

Creates one network per lemma (form + etymology), containing:
1. The lemma itself (main form with hieroglyphs)
2. Alternative forms (hieroglyphic/spelling variants)
3. Direct descendants (Demotic/Coptic) - as LEAF nodes (no further expansion)
4. Alternative forms of descendants
5. Parent words (for compounds) - as LEAF nodes (no further expansion)

Each network is ego-centric - focused on ONE lemma, not merged into mega-networks.

This version uses the new systematically parsed lemma files with 'sections' structure.
"""

import json
import re
from collections import defaultdict


class EgocentricLemmaNetworkBuilder:
    """Build ego-centric lemma networks - one per lemma etymology"""

    def __init__(self):
        self.networks = []  # List of networks (not dict by ID)
        self.next_node_id = 0
        self.next_network_id = 0

        # Egyptian chronological periods (for sorting)
        self.egyptian_periods = [
            'Predynastic', 'Early Dynastic', 'Old Kingdom', 'First Intermediate Period',
            'Middle Kingdom', 'Second Intermediate Period', 'New Kingdom',
            'Third Intermediate Period', 'Late Period', 'Ptolemaic', 'Roman'
        ]

    def get_new_node_id(self):
        """Generate a new unique node ID"""
        node_id = f"N{self.next_node_id:05d}"
        self.next_node_id += 1
        return node_id

    def get_new_network_id(self):
        """Generate a new unique network ID"""
        network_id = f"NET{self.next_network_id:05d}"
        self.next_network_id += 1
        return network_id

    def create_node(self, language, form, pos='unknown', meanings=None,
                    hieroglyphs=None, transliteration=None, period=None,
                    dialect=None, etymology_index=None, definition_index=None):
        """Create a node dictionary"""
        # Dialect can be a string or list
        if isinstance(dialect, list):
            dialect = ', '.join(dialect)

        node = {
            'node_id': self.get_new_node_id(),
            'language': language,
            'form': form,
            'pos': pos,
            'meanings': meanings or [],
            'hieroglyphs': hieroglyphs,
            'transliteration': transliteration,
            'period': period,
            'dialect': dialect,
            'etymology_index': etymology_index,
            'definition_index': definition_index
        }

        # Remove None values
        node = {k: v for k, v in node.items() if v is not None}
        return node

    def extract_hieroglyphs_from_params(self, params):
        """Extract hieroglyphs from template parameters"""
        if not params:
            return None

        # Look for hieroglyphic parameters
        hiero_patterns = [
            r'hiero\d*\s*=\s*([^|\n]+)',
            r'<hiero>(.*?)</hiero>',
            r'head\s*=\s*([^|\n]+)',
        ]

        for pattern in hiero_patterns:
            matches = re.findall(pattern, params, re.I)
            if matches:
                # Take the first non-empty match
                for match in matches:
                    hiero = match.strip()
                    if hiero and not hiero.startswith('{{'):
                        return hiero

        return None

    def is_alternative_form_of(self, meanings):
        """Check if this is an 'alternative form of' definition"""
        if not meanings:
            return False

        alt_patterns = [
            r'alternative form of',
            r'alt form of',
            r'variant of',
            r'see:?',
        ]

        for meaning in meanings:
            meaning_lower = meaning.lower()
            for pattern in alt_patterns:
                if pattern in meaning_lower:
                    return True

        return False

    def extract_etymology_mentions(self, text):
        """Extract etymology template mentions from text"""
        if not text:
            return []

        mentions = []

        # {{inh|lang|source|form|gloss}}
        inh_pattern = r'\{\{inh\|([^|}]+)\|([^|}]+)\|([^|}]*)\|?([^}]*)\}\}'
        for match in re.finditer(inh_pattern, text):
            lang, source, form, gloss = match.groups()
            mentions.append({
                'type': 'inh',
                'language': source.strip(),
                'form': form.strip() if form else '',
                'gloss': gloss.strip() if gloss else ''
            })

        # {{der|lang|source|form|gloss}}
        der_pattern = r'\{\{der\|([^|}]+)\|([^|}]+)\|([^|}]*)\|?([^}]*)\}\}'
        for match in re.finditer(der_pattern, text):
            lang, source, form, gloss = match.groups()
            mentions.append({
                'type': 'der',
                'language': source.strip(),
                'form': form.strip() if form else '',
                'gloss': gloss.strip() if gloss else ''
            })

        # {{bor|lang|source|form|gloss}}
        bor_pattern = r'\{\{bor\|([^|}]+)\|([^|}]+)\|([^|}]*)\|?([^}]*)\}\}'
        for match in re.finditer(bor_pattern, text):
            lang, source, form, gloss = match.groups()
            mentions.append({
                'type': 'bor',
                'language': source.strip(),
                'form': form.strip() if form else '',
                'gloss': gloss.strip() if gloss else ''
            })

        # {{m|lang|form|gloss}}
        m_pattern = r'\{\{m\|([^|}]+)\|([^|}]*)\|?([^}]*)\}\}'
        for match in re.finditer(m_pattern, text):
            lang, form, gloss = match.groups()
            mentions.append({
                'type': 'm',
                'language': lang.strip(),
                'form': form.strip() if form else '',
                'gloss': gloss.strip() if gloss else ''
            })

        return mentions

    def extract_alternative_forms_from_section(self, alt_section):
        """Extract alternative forms from an Alternative forms section"""
        alt_forms = []
        
        if not alt_section or not isinstance(alt_section, dict):
            return alt_forms
            
        content = alt_section.get('content', '')
        if not content:
            return alt_forms
            
        # Extract from {{egy-hieroforms ...}} templates
        for hf in re.finditer(r'\{\{egy-hieroforms(.*?)\}\}', content, flags=re.S|re.I):
            body = hf.group(1)
            # find readN= entries and hiero tags
            reads = re.findall(r'read\d*\s*=\s*([^\|\n]+)', body)
            hieros = re.findall(r'<hiero>(.*?)</hiero>', body, flags=re.S)
            dates = re.findall(r'date\d*\s*=\s*([^\|\n]+)', body)
            notes = re.findall(r'note\d*\s*=\s*([^\|\n]+)', body)
            
            # pair up reads with hieros/dates/notes if possible
            for idx, r in enumerate(reads):
                item = {'form': r.strip()}
                if idx < len(hieros):
                    item['hieroglyphs'] = hieros[idx].strip()
                if idx < len(dates):
                    item['date'] = dates[idx].strip()
                if idx < len(notes):
                    item['note'] = notes[idx].strip()
                alt_forms.append(item)
        
        return alt_forms

    def extract_forms_from_noun_and_inflection(self, sections):
        """Heuristic extraction of variant/inflection forms from Noun and Inflection sections.

        This helps when the Alternative forms section refers to "See under the noun above." or
        when variants appear in inflection lines rather than in structured {{egy-hieroforms}} templates.
        Returns a list of form strings or dicts with 'form' and optional 'hieroglyphs'.
        """
        forms = []
        if not sections or not isinstance(sections, dict):
            return forms

        candidates = []
        for name, data in sections.items():
            lname = name.lower()
            if any(k in lname for k in ('noun', 'inflection', 'inflections', 'plural', 'inflection table')):
                # gather raw content
                if isinstance(data, dict):
                    if 'content' in data and data.get('content'):
                        candidates.append(data.get('content'))
                    # definitions may contain alternative forms or templates
                    defs = data.get('definitions') or []
                    if isinstance(defs, list):
                        candidates.extend([d for d in defs if isinstance(d, str)])
                    # templates parsed into dicts (e.g., {'language':..., 'word':...})
                    templates = data.get('templates') or []
                    if isinstance(templates, list):
                        for t in templates:
                            if isinstance(t, dict):
                                # common parsed shape: {'language': 'cop-sah', 'word': '...'}
                                if 'word' in t and t.get('word'):
                                    forms.append(t.get('word'))
                                # some templates may include params like read1/read2
                                for k, v in t.items():
                                    if isinstance(v, str) and v.strip() and k.lower().startswith('read'):
                                        forms.append(v.strip())
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, str):
                            candidates.append(item)
                        elif isinstance(item, dict):
                            if 'word' in item:
                                forms.append(item.get('word'))
                            # include any 'form' keys
                            if 'form' in item:
                                forms.append(item.get('form'))

        # From candidate strings, extract token-like forms and {{m|egy|...}} templates
        mtempl = re.compile(r'\{\{m\|egy\|([^|}]+)', re.I)
        token_re = re.compile("([\\wꜣḥḫẖṯḏṣẓ]+|[^\\x00-\\x7F]+)")
        for c in candidates:
            if not c:
                continue
            # extract explicit m-template forms
            for m in mtempl.finditer(c):
                val = m.group(1).strip()
                if val:
                    forms.append(val)

            # fallback token extraction - be permissive to capture hieroglyphic translits
            for tok in re.findall(r"[A-Za-zꜣꜥḫḥṯḏṣẓ𓇋𓈖𓂋𓏏𓊹𓂝]+(?:[\-′']?[A-Za-zꜣꜥḫḥṯḏṣẓ𓇋𓈖𓂋𓏏𓊹𓂝]+)*", c):
                t = tok.strip()
                if t and len(t) > 0:
                    forms.append(t)

        # Normalize and dedupe preserving order
        out = []
        seen = set()
        for f in forms:
            if not f:
                continue
            fs = f.strip()
            if fs and fs not in seen:
                seen.add(fs)
                out.append(fs)

        return out

    def get_etymology_data_from_sections(self, sections):
        """Extract etymology data from the new sections format"""
        etymology_data = []

        # Find all etymology sections
        etymology_sections = {}
        pos_sections = {}

        for section_name, section_data in sections.items():
            section_lower = section_name.lower()

            if section_lower.startswith('etymology'):
                etymology_sections[section_name] = section_data
            elif section_lower in ['noun', 'verb', 'adjective', 'adverb', 'pronoun', 'preposition', 'conjunction', 'interjection', 'numeral', 'article', 'particle']:
                pos_sections[section_name] = section_data

        # For each etymology section, create etymology data
        for etym_name, etym_data in etymology_sections.items():
            etymology = {
                'etymology_text': etym_data.get('etymology_text', ''),
                'definitions': []
            }

            # Extract etymology ancestors
            ancestors = etym_data.get('etymology_ancestors', [])
            if ancestors:
                etymology['etymology_ancestors'] = ancestors

            # Extract etymology chain
            chain = etym_data.get('etymology_chain', [])
            if chain:
                etymology['etymology_chain'] = chain

            # Associate all POS sections with each etymology
            # (This is a simplification - real Wiktionary has complex etymology/POS relationships)
            for pos_name, pos_data in pos_sections.items():
                pos_lower = pos_name.lower()

                definitions = pos_data.get('definitions', [])
                for def_text in definitions:
                    def_entry = {
                        'part_of_speech': pos_lower,
                        'definitions': [def_text],
                        'hieroglyphs': pos_data.get('hieroglyphs'),
                        'parameters': pos_data.get('parameters', ''),
                        'usage_notes': pos_data.get('usage_notes'),
                        'alternative_forms': []
                    }
                    
                    # Extract alternative forms from the Alternative forms section
                    alt_section = sections.get('Alternative forms')
                    if alt_section:
                        alt_forms = self.extract_alternative_forms_from_section(alt_section)
                        def_entry['alternative_forms'] = alt_forms
                    
                    etymology['definitions'].append(def_entry)

            etymology_data.append(etymology)

        # If no etymology sections found, create one from available POS data
        if not etymology_data and pos_sections:
            etymology = {
                'etymology_text': 'No etymology available',
                'definitions': []
            }

            for pos_name, pos_data in pos_sections.items():
                pos_lower = pos_name.lower()

                definitions = pos_data.get('definitions', [])
                for def_text in definitions:
                    def_entry = {
                        'part_of_speech': pos_lower,
                        'definitions': [def_text],
                        'hieroglyphs': pos_data.get('hieroglyphs'),
                        'parameters': pos_data.get('parameters', ''),
                        'usage_notes': pos_data.get('usage_notes'),
                        'alternative_forms': []
                    }
                    
                    # Extract alternative forms from the Alternative forms section
                    alt_section = sections.get('Alternative forms')
                    if alt_section:
                        alt_forms = self.extract_alternative_forms_from_section(alt_section)
                        def_entry['alternative_forms'] = alt_forms
                    
                    etymology['definitions'].append(def_entry)

            etymology_data.append(etymology)

        # If still no data, create minimal entry
        if not etymology_data:
            etymology_data = [{
                'etymology_text': 'No data available',
                'definitions': [{
                    'part_of_speech': 'unknown',
                    'definitions': ['No definition available'],
                    'hieroglyphs': None,
                    'parameters': '',
                    'usage_notes': None
                }]
            }]

        return etymology_data

    def build_egyptian_networks(self, egy_data):
        """
        Build one network per Egyptian lemma etymology.
        Each network contains the main form + alternative forms.
        """
        networks = []

        for lemma_form, entry in egy_data.items():
            # Get etymology data from the new sections format
            sections = entry.get('sections', {})
            etymologies = self.get_etymology_data_from_sections(sections)

            for etym_idx, etymology in enumerate(etymologies):
                # Create network for this etymology
                network = {
                    'network_id': self.get_new_network_id(),
                    'root_lemma': lemma_form,
                    'root_language': 'egy',
                    'root_etymology_index': etym_idx,
                    'nodes': [],
                    'edges': []
                }

                # Track main nodes for each POS to create VARIANT edges between them
                pos_main_nodes = []

                # Track which descendants/derived terms we've added to avoid duplicates
                added_descendants = set()  # Track (language, form) pairs
                added_derived_terms = set()  # Track Egyptian derived forms

                # Process each definition in this etymology
                for defn_idx, defn in enumerate(etymology.get('definitions', [])):
                    pos = defn.get('part_of_speech', 'unknown')
                    meanings = defn.get('definitions', [])

                    # Skip if this is "alternative form of" another word
                    if self.is_alternative_form_of(meanings):
                        continue

                    # Extract hieroglyphs from definition or parameters
                    hieroglyphs = defn.get('hieroglyphs')
                    if not hieroglyphs:
                        params = defn.get('parameters', '')
                        hieroglyphs = self.extract_hieroglyphs_from_params(params)

                    # Strip <hiero> tags if present
                    if hieroglyphs:
                        hieroglyphs = re.sub(r'</?hiero>', '', hieroglyphs).strip()

                    # Create main lemma node for this POS
                    main_node = self.create_node(
                        language='egy',
                        form=lemma_form,
                        pos=pos,
                        meanings=meanings,
                        hieroglyphs=hieroglyphs,
                        etymology_index=etym_idx,
                        definition_index=defn_idx
                    )

                    network['nodes'].append(main_node)
                    pos_main_nodes.append(main_node)

                    # Collect alternative forms from several sources:
                    #  - definition-level alternative_forms
                    #  - etymology-level alternative_forms
                    #  - the top-level "Alternative forms" section (if present)
                    combined_alt_forms = []
                    # def-level
                    def_alt = defn.get('alternative_forms', []) or []
                    combined_alt_forms.extend(def_alt)
                    # etymology-level
                    ety_alt = etymology.get('alternative_forms', []) or []
                    combined_alt_forms.extend(ety_alt)
                    # global Alternative forms section (sections may contain alternative forms templates)
                    alt_section = sections.get('Alternative forms') or sections.get('Alternative Forms')
                    if alt_section:
                        combined_alt_forms.extend(self.extract_alternative_forms_from_section(alt_section))

                    # If still no or few alt forms, try heuristic extraction from Noun/Inflection sections
                    try:
                        noun_inf_forms = self.extract_forms_from_noun_and_inflection(sections)
                        if noun_inf_forms:
                            combined_alt_forms.extend(noun_inf_forms)
                    except Exception:
                        # don't fail the whole build on heuristic issues
                        pass

                    # Normalize and dedupe (by form string)
                    seen_alt_forms = set()
                    for alt_form in combined_alt_forms:
                        # alt_form may be a dict from extraction or a simple string
                        alt_form_str = None
                        alt_hiero = None
                        if isinstance(alt_form, dict):
                            alt_form_str = alt_form.get('form') or alt_form.get('reading')
                            alt_hiero = alt_form.get('hieroglyphs')
                        elif isinstance(alt_form, str):
                            alt_form_str = alt_form

                        if not alt_form_str:
                            continue
                        alt_form_str = alt_form_str.strip()
                        if alt_form_str == lemma_form or alt_form_str in seen_alt_forms:
                            continue
                        seen_alt_forms.add(alt_form_str)

                        alt_node = self.create_node(
                            language='egy',
                            form=alt_form_str,
                            pos=pos,
                            meanings=[f"Alternative form of {lemma_form}"],
                            hieroglyphs=alt_hiero,
                            etymology_index=etym_idx
                        )
                        network['nodes'].append(alt_node)

                        # Add VARIANT edge
                        network['edges'].append({
                            'source': main_node['node_id'],
                            'target': alt_node['node_id'],
                            'type': 'VARIANT',
                            'relation': 'spelling_variant'
                        })

                # Create VARIANT edges between different POS main nodes
                for i, node1 in enumerate(pos_main_nodes):
                    for j, node2 in enumerate(pos_main_nodes):
                        if i < j:  # Avoid duplicate edges
                            network['edges'].append({
                                'source': node1['node_id'],
                                'target': node2['node_id'],
                                'type': 'VARIANT',
                                'relation': 'pos_variant'
                            })

                # Add derived terms as Egyptian nodes
                # Collect derived terms from any 'derived' sections and etymology mentions
                derived_terms = []
                for section_name, section_data in sections.items():
                    if 'derived' in section_name.lower():
                        derived_data = section_data
                        if isinstance(derived_data, list):
                            derived_terms.extend(derived_data)
                        elif isinstance(derived_data, dict) and 'content' in derived_data:
                            # Extract token-like sequences (allow non-ascii glyphs)
                            content = derived_data['content']
                            # Split on common punctuation/whitespace to get candidate forms
                            terms = re.findall(r"([^\s,;()\[\]{}<>\\|]+)", content)
                            derived_terms.extend(terms)

                # Also scan etymology text and definitions for {{der|}}, {{inh|}} mentions
                etym_text = etymology.get('etymology_text', '')
                for mention in self.extract_etymology_mentions(etym_text):
                    if mention.get('language') in ('egy', 'egx', 'egyptian') and mention.get('form'):
                        derived_terms.append(mention.get('form'))
                for defn in etymology.get('definitions', []):
                    for meaning in defn.get('definitions', []):
                        for mention in self.extract_etymology_mentions(meaning):
                            if mention.get('language') in ('egy', 'egx', 'egyptian') and mention.get('form'):
                                derived_terms.append(mention.get('form'))

                # Normalize and dedupe
                cleaned_terms = []
                for t in derived_terms:
                    if not t:
                        continue
                    tf = t.strip()
                    if tf and tf != lemma_form and tf not in cleaned_terms:
                        cleaned_terms.append(tf)

                for derived_form in cleaned_terms:
                    if derived_form in added_derived_terms:
                        continue

                    # If the derived form exists in the Egyptian dataset, pull richer data
                    if derived_form in egy_data:
                        derived_entry = egy_data[derived_form]
                        derived_sections = derived_entry.get('sections', {})

                        # Get POS and meanings from the derived term
                        derived_pos = 'unknown'
                        derived_meanings = []
                        derived_hieroglyphs = None

                        for sec_name, sec_data in derived_sections.items():
                            if sec_name.lower() in ['noun', 'verb', 'adjective', 'adverb']:
                                derived_pos = sec_name.lower()
                                derived_meanings = sec_data.get('definitions', [])
                                derived_hieroglyphs = sec_data.get('hieroglyphs')
                                break

                    else:
                        # Create a placeholder node when the derived form isn't in the dataset
                        derived_pos = 'unknown'
                        derived_meanings = [f'Placeholder entry for {derived_form}']
                        derived_hieroglyphs = None

                    derived_node = self.create_node(
                        language='egy',
                        form=derived_form,
                        pos=derived_pos,
                        meanings=derived_meanings,
                        hieroglyphs=derived_hieroglyphs
                    )

                    network['nodes'].append(derived_node)
                    added_derived_terms.add(derived_form)

                    # Add DERIVED edge from each main node
                    for main_node in pos_main_nodes:
                        network['edges'].append({
                            'source': main_node['node_id'],
                            'target': derived_node['node_id'],
                            'type': 'DERIVED',
                            'relation': 'derived_from'
                        })

                networks.append(network)

        return networks

    def add_demotic_descendants(self, egy_networks, egy_data, dem_data):
        """Add Demotic descendants to Egyptian networks"""
        total_added = 0

        for network in egy_networks:
            root_form = network['root_lemma']
            # Track descendants we've already added for this network
            added_descendants = set()

            # Find descendants in Egyptian data
            if root_form in egy_data:
                sections = egy_data[root_form].get('sections', {})

                # First: process explicit 'descendant' sections as before
                for section_name, section_data in sections.items():
                    if 'descendant' in section_name.lower():
                        descendants = section_data
                        if isinstance(descendants, list):
                            for desc in descendants:
                                if isinstance(desc, dict) and desc.get('language') == 'egx-dem':
                                    dem_form = desc.get('word', desc.get('form', ''))
                                    if dem_form:
                                        if dem_form in dem_data:
                                            # Add Demotic node from dataset
                                            dem_entry = dem_data[dem_form]
                                            dem_sections = dem_entry.get('sections', {})

                                            dem_pos = 'unknown'
                                            dem_meanings = []
                                            dem_hieroglyphs = None

                                            for sec_name, sec_data in dem_sections.items():
                                                if sec_name.lower() in ['noun', 'verb', 'adjective', 'adverb']:
                                                    dem_pos = sec_name.lower()
                                                    dem_meanings = sec_data.get('definitions', [])
                                                    dem_hieroglyphs = sec_data.get('hieroglyphs')
                                                    break
                                        else:
                                            # Create placeholder Demotic node when no dataset entry exists
                                            dem_pos = 'unknown'
                                            dem_meanings = [f'Placeholder entry for {dem_form}']
                                            dem_hieroglyphs = None

                                        dem_node = self.create_node(
                                            language='egx-dem',
                                            form=dem_form,
                                            pos=dem_pos,
                                            meanings=dem_meanings,
                                            hieroglyphs=dem_hieroglyphs
                                        )

                                        network['nodes'].append(dem_node)
                                        total_added += 1

                                        # Add DESCENDS edge from Egyptian to Demotic
                                        for egy_node in network['nodes']:
                                            if egy_node['language'] == 'egy' and egy_node['form'] == root_form:
                                                network['edges'].append({
                                                    'source': egy_node['node_id'],
                                                    'target': dem_node['node_id'],
                                                    'type': 'INHERITED',
                                                    'relation': 'descends_to'
                                                })
                                                break

                # Second: scan all section content and etymology/definition text for etymology mentions
                # to catch forms expressed via templates like {{inh|...}} or {{der|...}}
                all_text = ''
                for sec in sections.values():
                    if isinstance(sec, dict):
                        all_text += ' ' + sec.get('content', '')
                        # also include definitions if available
                        defs = sec.get('definitions', [])
                        if isinstance(defs, list):
                            all_text += ' ' + ' '.join(defs)

                mentions = self.extract_etymology_mentions(all_text)
                for mention in mentions:
                    lang = (mention.get('language') or '').lower()
                    form = mention.get('form')
                    # consider demotic mentions where language contains 'dem'
                    if form and 'dem' in lang:
                        dem_form = form
                        # avoid duplicates
                        if ( 'egx-dem', dem_form ) in added_descendants:
                            continue
                        if dem_form in dem_data:
                            dem_entry = dem_data[dem_form]
                            dem_sections = dem_entry.get('sections', {})
                            dem_pos = 'unknown'
                            dem_meanings = []
                            dem_hieroglyphs = None
                            for sec_name, sec_data in dem_sections.items():
                                if sec_name.lower() in ['noun', 'verb', 'adjective', 'adverb']:
                                    dem_pos = sec_name.lower()
                                    dem_meanings = sec_data.get('definitions', [])
                                    dem_hieroglyphs = sec_data.get('hieroglyphs')
                                    break
                        else:
                            dem_pos = 'unknown'
                            dem_meanings = [f'Placeholder entry for {dem_form}']
                            dem_hieroglyphs = None

                        dem_node = self.create_node(
                            language='egx-dem',
                            form=dem_form,
                            pos=dem_pos,
                            meanings=dem_meanings,
                            hieroglyphs=dem_hieroglyphs
                        )
                        network['nodes'].append(dem_node)
                        added_descendants.add(('egx-dem', dem_form))
                        total_added += 1
                        for egy_node in network['nodes']:
                            if egy_node['language'] == 'egy' and egy_node['form'] == root_form:
                                network['edges'].append({
                                    'source': egy_node['node_id'],
                                    'target': dem_node['node_id'],
                                    'type': 'INHERITED',
                                    'relation': 'descends_to'
                                })
                                break

        return total_added

    def add_coptic_descendants(self, egy_networks, egy_data, cop_data):
        """Add Coptic descendants to Egyptian networks
        
        Handles both hierarchical (with level/children) and flat descendant structures.
        For desctree templates, attaches them to Coptic parents instead of Egyptian root.
        
        Supports two data structures:
        1. Old: {'sections': {'Descendants': [...]}}
        2. New: {'etymologies': [{'definitions': [{'descendants': [...]}]}]}
        """
        total_added = 0

        for network in egy_networks:
            root_form = network['root_lemma']

            # Find descendants in Egyptian data
            if root_form in egy_data:
                entry = egy_data[root_form]
                
                # Collect all descendants from different possible locations
                all_descendants = []
                
                # Check old structure: sections -> Descendants
                sections = entry.get('sections', {})
                for section_name, section_data in sections.items():
                    if 'descendant' in section_name.lower():
                        if isinstance(section_data, list):
                            all_descendants.extend(section_data)
                
                # Check new structure: etymologies -> definitions -> descendants
                etymologies = entry.get('etymologies', [])
                for etym in etymologies:
                    definitions = etym.get('definitions', [])
                    for defn in definitions:
                        descendants = defn.get('descendants', [])
                        if descendants:
                            all_descendants.extend(descendants)
                
                if all_descendants:
                    # First pass: add Coptic descendants and track them
                    coptic_nodes = {}  # form -> node

                    for desc in all_descendants:
                        if isinstance(desc, dict):
                            lang = desc.get('language', '')
                            
                            # Check if this is a Coptic descendant
                            if 'cop' in lang:
                                cop_form = desc.get('word', desc.get('form', ''))
                                if cop_form and cop_form != '-':
                                    # Add Coptic node from dataset
                                    if cop_form in cop_data:
                                        cop_entry = cop_data[cop_form]
                                        cop_sections = cop_entry.get('sections', {})

                                        cop_pos = 'unknown'
                                        cop_meanings = []
                                        cop_hieroglyphs = None

                                        for sec_name, sec_data in cop_sections.items():
                                            if sec_name.lower() in ['noun', 'verb', 'adjective', 'adverb']:
                                                cop_pos = sec_name.lower()
                                                cop_meanings = sec_data.get('definitions', [])
                                                cop_hieroglyphs = sec_data.get('hieroglyphs')
                                                break
                                    else:
                                        cop_pos = 'unknown'
                                        cop_meanings = [f'Placeholder entry for {cop_form}']
                                        cop_hieroglyphs = None

                                    cop_node = self.create_node(
                                        language=lang,
                                        form=cop_form,
                                        pos=cop_pos,
                                        meanings=cop_meanings,
                                        hieroglyphs=cop_hieroglyphs
                                    )

                                    network['nodes'].append(cop_node)
                                    coptic_nodes[cop_form] = cop_node
                                    total_added += 1

                                    # Add edge from Egyptian to Coptic
                                    for egy_node in network['nodes']:
                                        if egy_node['language'] == 'egy' and egy_node['form'] == root_form:
                                            network['edges'].append({
                                                'source': egy_node['node_id'],
                                                'target': cop_node['node_id'],
                                                'type': 'INHERITED',
                                                'relation': 'descends_to'
                                            })
                                            break

                    # Second pass: add descendants of Coptic or non-Coptic descendants
                    # These should be attached to Coptic parents if they exist
                    for desc in all_descendants:
                        if isinstance(desc, dict):
                            lang = desc.get('language', '')
                            template_type = desc.get('template_type', 'desc')
                            
                            # Skip Coptic descendants (already added in first pass)
                            if 'cop' in lang:
                                continue
                            
                            # Skip language markers (they don't represent actual descendants)
                            if desc.get('is_language_marker'):
                                continue
                            
                            child_form = desc.get('word', desc.get('form', ''))
                            
                            # Skip placeholders
                            if not child_form or child_form == '-':
                                continue
                            
                            # For desctree templates or other non-Coptic descendants,
                            # attach to Coptic parent if one exists, otherwise to Egyptian root
                            parent_node = None
                            
                            # Try to find a Coptic parent
                            if coptic_nodes:
                                # Use the first Coptic parent (in jmn-htp there's only one)
                                parent_node = next(iter(coptic_nodes.values()))
                            else:
                                # No Coptic parent, attach to Egyptian root
                                for node in network['nodes']:
                                    if node['language'] == 'egy' and node['form'] == root_form:
                                        parent_node = node
                                        break
                            
                            if parent_node:
                                # Create node for this descendant
                                child_node = self.create_node(
                                    language=lang,
                                    form=child_form,
                                    pos='unknown',
                                    meanings=[f'Descendant of {parent_node["form"]}'],
                                    hieroglyphs=None
                                )

                                network['nodes'].append(child_node)
                                total_added += 1

                                # Add edge from parent to child
                                network['edges'].append({
                                    'source': parent_node['node_id'],
                                    'target': child_node['node_id'],
                                    'type': 'INHERITED',
                                    'relation': 'descends_to'
                                })

                                # Handle children of this descendant (hierarchical descendants)
                                if desc.get('children'):
                                    for grandchild_desc in desc['children']:
                                        grandchild_lang = grandchild_desc.get('language', '')
                                        grandchild_form = grandchild_desc.get('word', grandchild_desc.get('form', ''))

                                        if grandchild_form and grandchild_form != '-':
                                            grandchild_node = self.create_node(
                                                language=grandchild_lang,
                                                form=grandchild_form,
                                                pos='unknown',
                                                meanings=[f'Descendant of {child_form}'],
                                                hieroglyphs=None
                                            )

                                            network['nodes'].append(grandchild_node)
                                            total_added += 1

                                            # Add edge from child to grandchild
                                            network['edges'].append({
                                                'source': child_node['node_id'],
                                                'target': grandchild_node['node_id'],
                                                'type': 'INHERITED',
                                                'relation': 'descends_to'
                                            })

        return total_added

    def build_demotic_standalone_networks(self, dem_data, egy_data):
        """Create standalone networks for Demotic lemmas without Egyptian ancestors"""
        networks = []

        for lemma_form, entry in dem_data.items():
            # Check if this Demotic lemma has Egyptian ancestors
            has_egyptian_ancestor = False

            sections = entry.get('sections', {})
            for section_name, section_data in sections.items():
                if 'etymology' in section_name.lower():
                    ancestors = section_data.get('etymology_ancestors', [])
                    for ancestor in ancestors:
                        if ancestor.get('language') == 'egy':
                            has_egyptian_ancestor = True
                            break

            if has_egyptian_ancestor:
                continue  # Skip, will be handled by add_demotic_descendants

            # Create standalone network
            network = {
                'network_id': self.get_new_network_id(),
                'root_lemma': lemma_form,
                'root_language': 'egx-dem',
                'root_etymology_index': 0,
                'nodes': [],
                'edges': []
            }

            # Add main node
            sections = entry.get('sections', {})
            dem_pos = 'unknown'
            dem_meanings = []
            dem_hieroglyphs = None

            for sec_name, sec_data in sections.items():
                if sec_name.lower() in ['noun', 'verb', 'adjective', 'adverb']:
                    dem_pos = sec_name.lower()
                    dem_meanings = sec_data.get('definitions', [])
                    dem_hieroglyphs = sec_data.get('hieroglyphs')
                    break

            main_node = self.create_node(
                language='egx-dem',
                form=lemma_form,
                pos=dem_pos,
                meanings=dem_meanings,
                hieroglyphs=dem_hieroglyphs
            )

            network['nodes'].append(main_node)
            networks.append(network)

        return networks

    def build_coptic_standalone_networks(self, cop_data, egy_data):
        """Create standalone networks for Coptic lemmas without Egyptian ancestors"""
        networks = []

        for lemma_form, entry in cop_data.items():
            # Check if this Coptic lemma has Egyptian ancestors
            has_egyptian_ancestor = False

            sections = entry.get('sections', {})
            for section_name, section_data in sections.items():
                if 'etymology' in section_name.lower():
                    ancestors = section_data.get('etymology_ancestors', [])
                    for ancestor in ancestors:
                        if ancestor.get('language') == 'egy':
                            has_egyptian_ancestor = True
                            break

            if has_egyptian_ancestor:
                continue  # Skip, will be handled by add_coptic_descendants

            # Create standalone network
            network = {
                'network_id': self.get_new_network_id(),
                'root_lemma': lemma_form,
                'root_language': 'cop',
                'root_etymology_index': 0,
                'nodes': [],
                'edges': []
            }

            # Add main node
            sections = entry.get('sections', {})
            cop_pos = 'unknown'
            cop_meanings = []
            cop_hieroglyphs = None

            for sec_name, sec_data in sections.items():
                if sec_name.lower() in ['noun', 'verb', 'adjective', 'adverb']:
                    cop_pos = sec_name.lower()
                    cop_meanings = sec_data.get('definitions', [])
                    cop_hieroglyphs = sec_data.get('hieroglyphs')
                    break

            main_node = self.create_node(
                language='cop',
                form=lemma_form,
                pos=cop_pos,
                meanings=cop_meanings,
                hieroglyphs=cop_hieroglyphs
            )

            network['nodes'].append(main_node)
            networks.append(network)

        return networks

    def build_networks_from_parsed_data(self, egy_data, dem_data, cop_data):
        """
        Build ego-centric lemma networks.

        Strategy:
        1. For each Egyptian lemma etymology, create ONE network
        2. Add alternative forms to that network
        3. Find descendants (Demotic/Coptic) and add them as leaf nodes
        4. Add alternative forms of descendants
        5. For compounds, add parent words as leaf nodes

        Returns: List of network dictionaries
        """
        print("Building ego-centric lemma networks...")
        print("="*80)

        # First pass: Build Egyptian lemma networks
        print("\n1. Building Egyptian lemma networks...")
        egy_networks = self.build_egyptian_networks(egy_data)
        print(f"   Created {len(egy_networks)} Egyptian lemma networks")

        # Second pass: Add descendants to Egyptian networks
        print("\n2. Adding Demotic descendants to Egyptian networks...")
        dem_count = self.add_demotic_descendants(egy_networks, egy_data, dem_data)
        print(f"   Added {dem_count} Demotic descendant nodes")

        print("\n3. Adding Coptic descendants to Egyptian networks...")
        cop_count = self.add_coptic_descendants(egy_networks, egy_data, cop_data)
        print(f"   Added {cop_count} Coptic descendant nodes")

        # Third pass: Create standalone networks for Demotic/Coptic lemmas without Egyptian ancestors
        print("\n4. Creating standalone Demotic networks...")
        dem_standalone = self.build_demotic_standalone_networks(dem_data, egy_data)
        print(f"   Created {len(dem_standalone)} standalone Demotic networks")

        print("\n5. Creating standalone Coptic networks...")
        cop_standalone = self.build_coptic_standalone_networks(cop_data, egy_data)
        print(f"   Created {len(cop_standalone)} standalone Coptic networks")

        # Combine all networks
        all_networks = egy_networks + dem_standalone + cop_standalone
        self.networks = all_networks

        print(f"\nTotal networks created: {len(all_networks)}")

        # Calculate totals
        total_nodes = sum(len(net['nodes']) for net in all_networks)
        total_edges = sum(len(net['edges']) for net in all_networks)

        print(f"Total nodes: {total_nodes}")
        print(f"Total edges: {total_edges}")

        return all_networks

    def export_networks(self, filename):
        """Export networks to JSON file"""
        print(f"\nExporting {len(self.networks)} networks to {filename}...")

        # Create export structure
        export_data = {
            'metadata': {
                'version': '3.0',
                'description': 'Ego-centric lemma networks with systematic section parsing',
                'total_networks': len(self.networks),
                'total_nodes': sum(len(net['nodes']) for net in self.networks),
                'total_edges': sum(len(net['edges']) for net in self.networks)
            },
            'networks': self.networks
        }

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        print("Export complete!")


def main():
    print("Lemma Network Builder V3 - Ego-centric Approach with Systematic Parsing")
    print("="*80)
    print()

    print("Loading systematically parsed Wiktionary data...")

    with open('egyptian_lemmas_new_parsed_mwp.json', 'r', encoding='utf-8') as f:
        egy_data = json.load(f)

    with open('demotic_lemmas_new_parsed_mwp.json', 'r', encoding='utf-8') as f:
        dem_data = json.load(f)

    with open('coptic_lemmas_new_parsed_mwp.json', 'r', encoding='utf-8') as f:
        cop_data = json.load(f)

    print(f"Loaded {len(egy_data)} Egyptian, {len(dem_data)} Demotic, {len(cop_data)} Coptic lemmas")

    # Build networks
    builder = EgocentricLemmaNetworkBuilder()
    networks = builder.build_networks_from_parsed_data(egy_data, dem_data, cop_data)

    # Export
    builder.export_networks('lemma_networks_v3.json')

    print("\n" + "="*80)
    print("Network building complete!")
    print("\nThe output file 'lemma_networks_v3.json' contains:")
    print("- Each network is ego-centric, focused on ONE lemma")
    print("- Nodes: the lemma, its variants, and direct descendants (as leaf nodes)")
    print("- Edges: VARIANT (spelling/hieroglyphic), INHERITED (cross-language)")
    print("\nThis can be used to visualize individual lemma evolution without sprawl.")


if __name__ == '__main__':
    main()