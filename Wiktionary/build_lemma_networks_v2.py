"""
Lemma Network Builder V2 - Ego-centric approach

Creates one network per lemma (form + etymology), containing:
1. The lemma itself (main form with hieroglyphs)
2. Alternative forms (hieroglyphic/spelling variants)
3. Direct descendants (Demotic/Coptic) - as LEAF nodes (no further expansion)
4. Alternative forms of descendants
5. Parent words (for compounds) - as LEAF nodes (no further expansion)

Each network is ego-centric - focused on ONE lemma, not merged into mega-networks.
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
    
    def create_node(self, language, form, pos='unknown', meanings=None, quotes=None,
                    hieroglyphs=None, transliteration=None, period=None, 
                    dialect=None, etymology_index=None, definition_index=None):
        """Create a node dictionary"""
        # Dialect can be a string or list
        if dialect and not isinstance(dialect, list):
            dialect = [dialect]
        
        return {
            'id': self.get_new_node_id(),
            'language': language,
            'form': form,
            'transliteration': transliteration or form,
            'hieroglyphs': hieroglyphs,
            'part_of_speech': pos,
            'meanings': meanings,
            'quotes': quotes or [],
            'quotes': quotes or [],
            'period': period,
            'dialects': dialect or [],  # Changed to plural and always a list
            'etymology_index': etymology_index,
            'definition_index': definition_index
        }
    
    def add_dialect_to_node(self, node, dialect):
        """Add a dialect to a node's dialect list if not already present"""
        if dialect and dialect not in node.get('dialects', []):
            if 'dialects' not in node:
                node['dialects'] = []
            node['dialects'].append(dialect)
    
    def create_edge(self, from_id, to_id, edge_type, notes=''):
        """Create an edge dictionary"""
        return {
            'from': from_id,
            'to': to_id,
            'type': edge_type,
            'notes': notes
        }
    
    def extract_period_from_date(self, date_str):
        """Extract standardized period from date string"""
        if not date_str:
            return None
        
        # Check for known periods
        for period in self.egyptian_periods:
            if period.lower() in date_str.lower():
                return period
        
        # Extract dynasty numbers
        dynasty_match = re.search(r'(\d+)(?:st|nd|rd|th)\s+Dynasty', date_str, re.IGNORECASE)
        if dynasty_match:
            return f"{dynasty_match.group(1)}th Dynasty"
        
        return date_str  # Return as-is if we can't standardize
    
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
    
    def get_period_rank(self, period):
        """Get chronological ranking of a period (lower = earlier)"""
        if not period:
            return 999
        
        # Textual periods
        period_rankings = {
            'Predynastic': 0,
            'Early Dynastic': 1,
            'Pyramid Texts': 2,
            'Old Kingdom': 2,
            'First Intermediate Period': 3,
            'Middle Kingdom': 4,
            'Coffin Texts': 4,  # Middle Kingdom era
            'Second Intermediate Period': 5,
            'New Kingdom': 6,
            'Book of the Dead': 6,  # New Kingdom era
            'Third Intermediate Period': 7,
            'Late Period': 8,
            'Late Egyptian': 8,
            'Ptolemaic': 9,
            'Ptolemaic Period': 9,
            'Roman': 10,
            'Greco-Roman Period': 10,
        }
        
        # Check if period is in our known rankings
        for known_period, rank in period_rankings.items():
            if known_period.lower() in period.lower():
                return rank
        
        # Dynasty numbers (approximate chronology)
        dynasty_match = re.search(r'(\d+)(?:st|nd|rd|th)', period)
        if dynasty_match:
            dynasty_num = int(dynasty_match.group(1))
            # Map dynasties to approximate periods
            if dynasty_num <= 2:
                return 1  # Early Dynastic
            elif dynasty_num <= 6:
                return 2  # Old Kingdom
            elif dynasty_num <= 11:
                return 3  # First Intermediate Period
            elif dynasty_num <= 13:
                return 4  # Middle Kingdom
            elif dynasty_num <= 17:
                return 5  # Second Intermediate Period
            elif dynasty_num <= 20:
                return 6  # New Kingdom
            elif dynasty_num <= 25:
                return 7  # Third Intermediate Period
            elif dynasty_num <= 31:
                return 8  # Late Period
            else:
                return 9  # Ptolemaic/Greco-Roman
        
        # Default: unknown period
        return 500
    
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
        cop_standalone = self.build_coptic_standalone_networks(cop_data, egy_data, dem_data)
        print(f"   Created {len(cop_standalone)} standalone Coptic networks")
        
        # Combine all networks
        self.networks = egy_networks + dem_standalone + cop_standalone
        
        # Clean up redundant edges
        print(f"\n6. Cleaning up redundant descendant edges...")
        removed_count = self.cleanup_redundant_descendant_edges()
        print(f"   Removed {removed_count} redundant edges")
        
        print(f"\n{'='*80}")
        print(f"Total networks created: {len(self.networks)}")
        print(f"  - Egyptian-rooted: {len(egy_networks)}")
        print(f"  - Demotic-rooted: {len(dem_standalone)}")
        print(f"  - Coptic-rooted: {len(cop_standalone)}")
        
        return self.networks
    
    def build_egyptian_networks(self, egy_data):
        """
        Build one network per Egyptian lemma etymology.
        Each network contains the main form + alternative forms.
        """
        networks = []
        debug_count = 0
        total_defs_processed = 0
        
        for lemma_form, entry in egy_data.items():
            etymologies = entry.get('etymologies', [])
            
            for etym_idx, etymology in enumerate(etymologies):
                # Process each definition in this etymology
                # Create ONE network per definition (POS/meaning), not one per etymology
                for defn_idx, defn in enumerate(etymology.get('definitions', [])):
                    total_defs_processed += 1
                    # Create network for THIS DEFINITION
                    network = {
                        'network_id': self.get_new_network_id(),
                        'root_lemma': lemma_form,
                        'root_language': 'egy',
                        'root_etymology_index': etym_idx,
                        'root_definition_index': defn_idx,
                        'nodes': [],
                        'edges': []
                    }
                    
                    # Track main nodes for each POS to create VARIANT edges between them
                    pos_main_nodes = []
                    
                    # Track which descendants/derived terms we've added to avoid duplicates
                    added_descendants = set()  # Track (language, form) pairs
                    added_derived_terms = set()  # Track Egyptian derived forms
                    pos = defn.get('part_of_speech', 'unknown')
                    meanings = defn.get('definitions', [])
                    quotes = defn.get('quotes', [])
                    
                    # Extract hieroglyphs from definition or parameters
                    hieroglyphs = defn.get('hieroglyphs')
                    if not hieroglyphs:
                        params = defn.get('parameters', {})
                        hieroglyphs = self.extract_hieroglyphs_from_params(params)
                    
                    # Strip <hiero> tags if present
                    if hieroglyphs:
                        hieroglyphs = re.sub(r'</?hiero>', '', hieroglyphs).strip()
                    
                    # Create main lemma node for this POS
                    main_node = self.create_node(
                        language='egy',
                        form=lemma_form,
                        pos=pos,
                        meanings=meanings, quotes=quotes,
                        hieroglyphs=hieroglyphs,
                        etymology_index=etym_idx,
                        definition_index=defn_idx  # Track which definition this is
                    )
                    network['nodes'].append(main_node)
                    pos_main_nodes.append(main_node)
                    
                    if lemma_form == 'ꜣ' and etym_idx == 0 and defn_idx == 0:
                        pass
                    
                    # Add alternative forms as variant nodes with temporal evolution
                    # Group by inflection type (base, plural, godhood, etc.) for separate chains
                    alt_forms = defn.get('alternative_forms', [])
                    
                    # Organize alternative forms by type (base, plural, dual, fem, godhood, etc.)
                    alt_forms_by_type = {}  # type -> list of form data
                    
                    for alt in alt_forms:
                        alt_hieroglyphs = alt.get('hieroglyphs')
                        # Strip <hiero> tags from alternative forms
                        if alt_hieroglyphs:
                            alt_hieroglyphs = re.sub(r'</?hiero>', '', alt_hieroglyphs).strip()
                        
                        alt_translit = alt.get('transliteration') or alt.get('form') or lemma_form
                        period = self.extract_period_from_date(alt.get('date'))
                        period_rank = self.get_period_rank(period) if period else 999
                        title = alt.get('title', '')
                        note = alt.get('note', '')
                        
                        # Detect type from title/note
                        type_info = f"{title} {note}".lower()
                        alt_type = 'base'  # Default type
                        
                        # Check for special types
                        if 'plural' in type_info or 'pl.' in type_info:
                            alt_type = 'plural'
                        elif 'dual' in type_info:
                            alt_type = 'dual'
                        elif 'feminine' in type_info or 'fem.' in type_info:
                            alt_type = 'feminine'
                        elif 'god' in type_info or 'deity' in type_info or 'divine' in type_info:
                            alt_type = 'godhood'
                        elif 'determinative' in type_info:
                            alt_type = 'determinative'
                        
                        # Create variant node
                        variant_node = self.create_node(
                            language='egy',
                            form=alt_translit,
                            pos=pos,
                            meanings=meanings, quotes=quotes,  # Same meanings as main form
                            hieroglyphs=alt_hieroglyphs,
                            transliteration=alt_translit,
                            period=period,
                            etymology_index=etym_idx,
                            definition_index=defn_idx
                        )
                        network['nodes'].append(variant_node)
                        
                        # Add to type group
                        if alt_type not in alt_forms_by_type:
                            alt_forms_by_type[alt_type] = []
                        
                        alt_forms_by_type[alt_type].append({
                            'node': variant_node,
                            'period': period,
                            'period_rank': period_rank,
                            'type': alt_type
                        })
                    
                    # Create temporal edges for EACH type separately
                    # Track the latest form node (for descendants)
                    latest_form_node = main_node
                    latest_period_rank = 999
                    
                    for alt_type, alt_forms_data in alt_forms_by_type.items():
                        # Sort by period rank (chronological order)
                        alt_forms_data.sort(key=lambda x: x['period_rank'])
                        
                        # Group forms by period within this type
                        by_period = {}
                        for form_data in alt_forms_data:
                            period_rank = form_data['period_rank']
                            if period_rank not in by_period:
                                by_period[period_rank] = []
                            by_period[period_rank].append(form_data)
                        
                        # Get sorted periods
                        sorted_periods = sorted(by_period.keys())
                        dated_periods = [p for p in sorted_periods if p < 500]
                        undated_forms = by_period.get(999, [])
                        
                        # Connect main node to earliest dated form of this type
                        if dated_periods:
                            # Connect main to earliest dated alternative of this type
                            earliest_forms = by_period[dated_periods[0]]
                            
                            # Determine edge type based on alt_type
                            if alt_type == 'base':
                                edge_type = 'EVOLVES'
                                notes = f"First attestation in {earliest_forms[0]['period']}"
                            else:
                                edge_type = 'DERIVED'
                                notes = f"{alt_type.capitalize()} form from {earliest_forms[0]['period']}"
                            
                            edge = self.create_edge(
                                from_id=main_node['id'],
                                to_id=earliest_forms[0]['node']['id'],
                                edge_type=edge_type,
                                notes=notes
                            )
                            network['edges'].append(edge)
                            
                            # Create EVOLVES edges between chronologically consecutive forms
                            for i in range(len(dated_periods) - 1):
                                current_period = dated_periods[i]
                                next_period = dated_periods[i + 1]
                                
                                current_forms = by_period[current_period]
                                next_forms = by_period[next_period]
                                
                                # Connect last form of current period to first form of next period
                                edge = self.create_edge(
                                    from_id=current_forms[-1]['node']['id'],
                                    to_id=next_forms[0]['node']['id'],
                                    edge_type='EVOLVES',
                                    notes=f"Evolution from {current_forms[-1]['period']} to {next_forms[0]['period']}"
                                )
                                network['edges'].append(edge)
                                
                                # Create VARIANT edges within same period - ALL forms connect to each other
                                if len(current_forms) > 1:
                                    for j in range(len(current_forms)):
                                        for k in range(j + 1, len(current_forms)):
                                            edge = self.create_edge(
                                                from_id=current_forms[j]['node']['id'],
                                                to_id=current_forms[k]['node']['id'],
                                                edge_type='VARIANT',
                                                notes=f"Hieroglyphic variant ({current_forms[j]['period']})"
                                            )
                                            network['edges'].append(edge)
                            
                            # Handle variants in the last period - ALL forms connect to each other
                            if len(by_period[dated_periods[-1]]) > 1:
                                last_period_forms = by_period[dated_periods[-1]]
                                for j in range(len(last_period_forms)):
                                    for k in range(j + 1, len(last_period_forms)):
                                        edge = self.create_edge(
                                            from_id=last_period_forms[j]['node']['id'],
                                            to_id=last_period_forms[k]['node']['id'],
                                            edge_type='VARIANT',
                                            notes=f"Hieroglyphic variant ({last_period_forms[j]['period']})"
                                        )
                                        network['edges'].append(edge)
                            
                            # Track the overall latest form (across all types) for descendants
                            # Only base forms should be considered for descendants
                            if alt_type == 'base':
                                last_period_rank = dated_periods[-1]
                                if last_period_rank < latest_period_rank:
                                    latest_period_rank = last_period_rank
                                    latest_form_node = by_period[dated_periods[-1]][-1]['node']
                        
                        # If only undated forms, connect them as variants/derived to main node
                        elif undated_forms:
                            for form_data in undated_forms:
                                if alt_type == 'base':
                                    edge_type = 'VARIANT'
                                    notes = 'Hieroglyphic variant (undated)'
                                else:
                                    edge_type = 'DERIVED'
                                    notes = f'{alt_type.capitalize()} form (undated)'
                                
                                edge = self.create_edge(
                                    from_id=main_node['id'],
                                    to_id=form_data['node']['id'],
                                    edge_type=edge_type,
                                    notes=notes
                                )
                                network['edges'].append(edge)
                    
                    # Add descendants listed in this definition (hierarchical)
                    descendants = defn.get('descendants', [])
                    
                    def process_descendants_recursive(desc_list, parent_node, parent_lang):
                        """Recursively process descendants and their children.
                        
                        When a descendant has edge_type='borrowed', it attaches to the 
                        previously processed sibling node (the 'last word mentioned') 
                        rather than to the parent. This models that e.g. Old Nubian 
                        borrowed from Demotic, not directly from Egyptian.
                        """
                        last_inherited_node = None  # Track most recent inherited sibling for bor=1
                        last_inherited_lang = None
                        
                        for desc in desc_list:
                            desc_lang = desc.get('language', '')
                            desc_word = desc.get('word', '').split('<')[0].strip()
                            desc_children = desc.get('children', [])
                            desc_edge_type = desc.get('edge_type', 'inherited')
                            
                            # Resolve nested templates like {{l|egx-dem|pr-ꜥꜣ}}
                            if desc_word and '{{' in desc_word:
                                import re
                                nested = re.search(r'\{\{(?:l|m|link|mention)\|[^|]+\|([^|}]+)', desc_word)
                                if nested:
                                    desc_word = nested.group(1).strip()
                                else:
                                    continue  # Skip unresolvable template text
                            
                            if not desc_word:
                                continue
                            
                            # Map language codes to our standard codes
                            lang_map = {
                                'egx-dem': 'dem',
                                'cop-akh': 'cop',
                                'cop-sah': 'cop',
                                'cop-boh': 'cop',
                                'cop-fay': 'cop',
                                'cop-lyc': 'cop',
                                'cop-old': 'cop',  # Old Coptic
                                'cop-oxy': 'cop'   # Oxyrhynchite Coptic
                            }
                            
                            standard_lang = lang_map.get(desc_lang, desc_lang)
                            
                            # Determine the actual parent for this descendant:
                            # - If borrowed (bor=1), attach to the last INHERITED sibling
                            #   (e.g. both Old Nubian AND Greek borrow from Demotic)
                            # - Otherwise attach to the parent_node (normal inheritance)
                            if desc_edge_type == 'borrowed' and last_inherited_node is not None:
                                effective_parent = last_inherited_node
                                effective_parent_lang = last_inherited_lang
                                edge_label = 'BORROWED'
                            else:
                                effective_parent = parent_node
                                effective_parent_lang = parent_lang
                                edge_label = 'INHERITED'
                            
                            # Process Egyptian-family languages (dem, cop) with full descendant tracking
                            # Process other languages (Greek, Arabic, etc.) as leaf nodes only
                            if standard_lang in ['dem', 'cop']:
                                # Check if node already exists
                                desc_key = (standard_lang, desc_word)
                                existing_node = next((n for n in network['nodes'] 
                                                     if n['language'] == standard_lang and n['form'] == desc_word), None)
                                
                                if existing_node:
                                    # Node exists - add dialect info and create edge if needed
                                    if standard_lang == 'cop':
                                        self.add_dialect_to_node(existing_node, desc_lang)
                                    
                                    # Create edge from effective parent if not already connected
                                    edge_exists = any(e['from'] == effective_parent['id'] and e['to'] == existing_node['id'] 
                                                     for e in network['edges'])
                                    if not edge_exists:
                                        edge = self.create_edge(
                                            from_id=effective_parent['id'],
                                            to_id=existing_node['id'],
                                            edge_type=edge_label,
                                            notes=f'{effective_parent_lang.title()} → {standard_lang.title()}'
                                        )
                                        network['edges'].append(edge)
                                    
                                    # Process children
                                    if desc_children:
                                        process_descendants_recursive(desc_children, existing_node, standard_lang)
                                    
                                    # Track as last-inherited for subsequent borrowed siblings
                                    if desc_edge_type != 'borrowed':
                                        last_inherited_node = existing_node
                                        last_inherited_lang = standard_lang
                                
                                elif desc_key not in added_descendants:
                                    # Node doesn't exist - create it
                                    added_descendants.add(desc_key)
                                    
                                    desc_node = self.create_node(
                                        language=standard_lang,
                                        form=desc_word,
                                        pos=pos,  # Assume same POS as parent
                                        meanings=[],  # No meaning info from desc template
                                        dialect=desc_lang if standard_lang == 'cop' else None
                                    )
                                    network['nodes'].append(desc_node)
                                    
                                    # Create edge from effective parent to this descendant
                                    edge = self.create_edge(
                                        from_id=effective_parent['id'],
                                        to_id=desc_node['id'],
                                        edge_type=edge_label,
                                        notes=f'{effective_parent_lang.title()} → {standard_lang.title()}'
                                    )
                                    network['edges'].append(edge)
                                    
                                    # Recursively process children of this descendant
                                    if desc_children:
                                        process_descendants_recursive(desc_children, desc_node, standard_lang)
                                    
                                    # Track as last-inherited for subsequent borrowed siblings
                                    if desc_edge_type != 'borrowed':
                                        last_inherited_node = desc_node
                                        last_inherited_lang = standard_lang
                            
                            else:
                                # Non-Egyptian language (Greek, Arabic, etc.) - add as leaf node
                                desc_key = (standard_lang, desc_word)
                                
                                # Check if already added
                                existing_node = next((n for n in network['nodes'] 
                                                     if n['language'] == standard_lang and n['form'] == desc_word), None)
                                
                                if not existing_node and desc_key not in added_descendants:
                                    added_descendants.add(desc_key)
                                    
                                    # Create leaf node for non-Egyptian descendant
                                    desc_node = self.create_node(
                                        language=standard_lang,
                                        form=desc_word,
                                        pos=pos,
                                        meanings=[],
                                        dialect=None
                                    )
                                    network['nodes'].append(desc_node)
                                    
                                    # Create edge from effective parent
                                    edge = self.create_edge(
                                        from_id=effective_parent['id'],
                                        to_id=desc_node['id'],
                                        edge_type=edge_label,
                                        notes=f'{effective_parent_lang.title()} → {standard_lang.title()}'
                                    )
                                    network['edges'].append(edge)
                                    
                                    # Add immediate children as leaf nodes (one level only)
                                    if desc_children:
                                        for child in desc_children:
                                            child_lang = child.get('language', '')
                                            child_word = child.get('word', '')
                                            if child_lang and child_word:
                                                child_key = (child_lang, child_word)
                                                if child_key not in added_descendants:
                                                    added_descendants.add(child_key)
                                                    
                                                    child_node = self.create_node(
                                                        language=child_lang,
                                                        form=child_word,
                                                        pos=pos,
                                                        meanings=[],
                                                        dialect=None
                                                    )
                                                    network['nodes'].append(child_node)
                                                    
                                                    # Edge from non-Egyptian parent to child
                                                    edge = self.create_edge(
                                                        from_id=desc_node['id'],
                                                        to_id=child_node['id'],
                                                        edge_type='INHERITED',
                                                        notes=f'{standard_lang.title()} → {child_lang.title()}'
                                                    )
                                                    network['edges'].append(edge)
                                    
                                    # Track as last-inherited for subsequent borrowed siblings
                                    if desc_edge_type != 'borrowed':
                                        last_inherited_node = desc_node
                                        last_inherited_lang = standard_lang
                                    
                                elif existing_node:
                                    # Node exists - just add edge if needed
                                    edge_exists = any(e['from'] == effective_parent['id'] and e['to'] == existing_node['id'] 
                                                     for e in network['edges'])
                                    if not edge_exists:
                                        edge = self.create_edge(
                                            from_id=effective_parent['id'],
                                            to_id=existing_node['id'],
                                            edge_type=edge_label,
                                            notes=f'{effective_parent_lang.title()} → {standard_lang.title()}'
                                        )
                                        network['edges'].append(edge)
                                    
                                    if desc_edge_type != 'borrowed':
                                        last_inherited_node = existing_node
                                        last_inherited_lang = standard_lang
                    
                    # Start recursive processing with latest_form_node as root
                    # Descendants descend from the LATEST dated form (or main if no dated forms)
                    process_descendants_recursive(descendants, latest_form_node, 'egy')
                    
                    # Add derived terms listed in this definition
                    derived_terms = defn.get('derived_terms', [])
                    for derived_form in derived_terms:
                        if not derived_form or derived_form == lemma_form:
                            continue
                        
                        # Skip if already added
                        if derived_form in added_derived_terms:
                            continue
                        added_derived_terms.add(derived_form)

                        # Try to enrich derived term from parsed Egyptian data
                        derived_pos = 'unknown'
                        derived_meanings = []
                        derived_hieroglyphs = None
                        derived_translit = derived_form

                        derived_entry = egy_data.get(derived_form)
                        if derived_entry:
                            # Pull first etymology/definition if available
                            etys = derived_entry.get('etymologies', [])
                            if etys:
                                first_et = etys[0]
                                defs = first_et.get('definitions', [])
                                if defs:
                                    d0 = defs[0]
                                    derived_pos = d0.get('part_of_speech', derived_pos)
                                    # meanings may be under 'definitions' key for parsed defs
                                    derived_meanings = d0.get('definitions', []) or []
                                    # extract hieroglyphs from explicit field or parameters
                                    derived_hieroglyphs = d0.get('hieroglyphs') or self.extract_hieroglyphs_from_params(d0.get('parameters', {}))
                                    if derived_hieroglyphs:
                                        derived_hieroglyphs = re.sub(r'</?hiero>', '', derived_hieroglyphs).strip()
                                    # transliteration if present
                                    derived_translit = d0.get('transliteration') or derived_translit

                        # Fallback meaning if none found
                        if not derived_meanings:
                            derived_meanings = [f'Derived from {lemma_form}']

                        # Create derived term node (Egyptian)
                        derived_node = self.create_node(
                            language='egy',
                            form=derived_form,
                            pos=derived_pos,
                            meanings=derived_meanings,
                            hieroglyphs=derived_hieroglyphs,
                            transliteration=derived_translit,
                            etymology_index=etym_idx
                        )
                        network['nodes'].append(derived_node)

                        # Create DERIVED edge
                        edge = self.create_edge(
                            from_id=main_node['id'],
                            to_id=derived_node['id'],
                            edge_type='DERIVED',
                            notes=f'Derived term'
                        )
                        network['edges'].append(edge)
                
                # Process etymology components (for compound words)
                # If this lemma is a compound, add its component words to the network
                etymology_components = etymology.get('etymology_components', [])
                if etymology_components and pos_main_nodes:
                    # Use the first main node as the compound word node
                    compound_node = pos_main_nodes[0]
                    
                    for component in etymology_components:
                        component_form = component.get('form', '')
                        if not component_form or component_form == lemma_form:
                            continue
                        
                        # Look for this component in other networks or create a stub node
                        component_network = self.find_egyptian_network(networks, component_form)
                        
                        # Check if we already have this component in the current network
                        existing_component = next((n for n in network['nodes'] 
                                                  if n['language'] == 'egy' and n['form'] == component_form), None)
                        
                        if existing_component:
                            component_node = existing_component
                        elif component_network and component_network['nodes']:
                            # Use the first node from the component's network as reference
                            # Create a copy in this network
                            ref_node = component_network['nodes'][0]
                            component_node = self.create_node(
                                language='egy',
                                form=component_form,
                                pos=ref_node.get('part_of_speech', 'unknown'),
                                meanings=ref_node.get('meanings', []),
                                hieroglyphs=ref_node.get('hieroglyphs'),
                                etymology_index=ref_node.get('etymology_index')
                            )
                            network['nodes'].append(component_node)
                        else:
                            # Create stub node for component
                            component_node = self.create_node(
                                language='egy',
                                form=component_form,
                                pos='unknown',
                                meanings=[f'Component of {lemma_form}'],
                                etymology_index=etym_idx
                            )
                            network['nodes'].append(component_node)
                        
                        # Create COMPONENT edge from component to compound
                        edge = self.create_edge(
                            from_id=component_node['id'],
                            to_id=compound_node['id'],
                            edge_type='COMPONENT',
                            notes=f'Component of compound word'
                        )
                        network['edges'].append(edge)
                
                # Process etymology chain from etymology text
                # Parse "from X, from Y, from Z" to create proper chain: Z → Y → X → current
                etymology_text = etymology.get('etymology_text', '')
                if etymology_text and pos_main_nodes:
                    target_node = pos_main_nodes[0]
                    
                    # Parse etymology chain
                    chain = self.parse_etymology_chain(etymology_text)
                    
                    # Normalize language codes
                    lang_map = {
                        'egx-dem': 'dem',
                        'cop-akh': 'cop', 'cop-sah': 'cop', 'cop-boh': 'cop',
                        'cop-fay': 'cop', 'cop-lyc': 'cop', 'cop-oxy': 'cop'
                    }
                    
                    # Create nodes for chain items
                    chain_nodes = []
                    for item in chain:
                        item_lang = lang_map.get(item['language'], item['language'])
                        item_form = item['form']
                        item_gloss = item['gloss']
                        item_type = item['type']
                        
                        if not item_form or not item_lang:
                            continue
                        
                        # Check if node already exists
                        existing_node = next((n for n in network['nodes']
                                            if n['language'] == item_lang and n['form'] == item_form), None)
                        
                        if not existing_node:
                            # Create node
                            meanings = [item_gloss] if item_gloss else []
                            
                            # If no gloss and Egyptian-family, infer from target
                            if not meanings and item_lang in ['egy', 'dem', 'cop']:
                                target_meanings = target_node.get('meanings', [])
                                if target_meanings:
                                    meanings = [f"Earlier form; cf. {target_meanings[0][:50]}"]
                            
                            node = self.create_node(
                                language=item_lang,
                                form=item_form,
                                pos='unknown',
                                meanings=meanings, quotes=quotes,
                                etymology_index=None
                            )
                            network['nodes'].append(node)
                            chain_nodes.append({'node': node, 'type': item_type})
                        else:
                            # Add gloss if not already there
                            if item_gloss and item_gloss not in existing_node.get('meanings', []):
                                if 'meanings' not in existing_node:
                                    existing_node['meanings'] = []
                                existing_node['meanings'].append(item_gloss)
                            chain_nodes.append({'node': existing_node, 'type': item_type})
                    
                    # Create chain edges: oldest → ... → newest → target
                    # chain is already ordered oldest to newest
                    for i in range(len(chain_nodes)):
                        if i < len(chain_nodes) - 1:
                            # Link to next in chain
                            from_node = chain_nodes[i]['node']
                            to_node = chain_nodes[i + 1]['node']
                            item_type = chain_nodes[i + 1]['type']
                        else:
                            # Link last chain item to target
                            from_node = chain_nodes[i]['node']
                            to_node = target_node
                            item_type = chain_nodes[i]['type']
                        
                        # Check if edge already exists
                        edge_exists = any(e['from'] == from_node['id'] and e['to'] == to_node['id']
                                        for e in network['edges'])
                        if edge_exists:
                            continue
                        
                        # Determine edge type
                        from_lang = from_node['language']
                        to_lang = to_node['language']
                        
                        if item_type == 'inh':
                            edge_type = 'INHERITED'
                        elif item_type == 'bor':
                            edge_type = 'BORROWED'
                        elif item_type == 'der':
                            edge_type = 'DERIVED'
                        else:
                            # {{m}} or {{l}} - use INHERITED for cross-language, VARIANT for same-language
                            if from_lang != to_lang:
                                edge_type = 'INHERITED'
                            else:
                                edge_type = 'VARIANT'
                        
                        edge = self.create_edge(
                            from_id=from_node['id'],
                            to_id=to_node['id'],
                            edge_type=edge_type,
                            notes=f'{from_lang.title()} → {to_lang.title()}'
                        )
                        network['edges'].append(edge)
                
                    # Only add network if it has nodes (inside defn loop)
                    if network['nodes']:
                        networks.append(network)
        
        print(f"   DEBUG: Total definitions processed: {total_defs_processed}")
        print(f"   DEBUG: Created networks: {len(networks)}")
        return networks
    
    def is_alternative_form_of(self, meanings):
        """Check if meanings indicate this is an alternative form of another word"""
        if not meanings:
            return False
        
        first_meaning = meanings[0].lower()
        return (first_meaning.startswith('alternative form of') or 
                first_meaning.startswith('alternative spelling of'))
    
    def cleanup_redundant_descendant_edges(self):
        """
        Clean up redundant INHERITED edges:
        1. Remove edges from early Egyptian forms if descendant already connects from latest form
        2. Remove direct Egyptian→Coptic edges if there's an Egyptian→Demotic→Coptic path
        
        Returns: count of removed edges
        """
        removed_count = 0
        
        for network in self.networks:
            edges_to_remove = []
            
            # Get all Egyptian nodes and sort by period
            egy_nodes = [n for n in network['nodes'] if n['language'] == 'egy']
            if len(egy_nodes) <= 1:
                continue  # No cleanup needed if only one Egyptian node
            
            # Sort Egyptian nodes by period rank to identify earliest and latest
            egy_nodes_with_rank = []
            for node in egy_nodes:
                period = node.get('period')
                rank = self.get_period_rank(period) if period else 999
                egy_nodes_with_rank.append({'node': node, 'rank': rank})
            
            egy_nodes_with_rank.sort(key=lambda x: x['rank'])
            
            # Find the latest DATED form, or fall back to undated main form
            # Latest = highest rank among DATED forms (rank < 500)
            dated_nodes = [n for n in egy_nodes_with_rank if n['rank'] < 500]
            if dated_nodes:
                latest_egy_node = dated_nodes[-1]['node']  # Last (highest rank) dated node
            else:
                # No dated forms, use the first undated node (main form)
                latest_egy_node = egy_nodes_with_rank[0]['node']
            
            # Get all INHERITED edges
            inherited_edges = [e for e in network['edges'] if e['type'] == 'INHERITED']
            
            # Build a map of what descendants connect from which Egyptian nodes
            egy_to_descendants = {}  # egy_id -> set of descendant_ids
            for edge in inherited_edges:
                from_node = next((n for n in network['nodes'] if n['id'] == edge['from']), None)
                to_node = next((n for n in network['nodes'] if n['id'] == edge['to']), None)
                
                if from_node and to_node and from_node['language'] == 'egy':
                    if from_node['id'] not in egy_to_descendants:
                        egy_to_descendants[from_node['id']] = set()
                    egy_to_descendants[from_node['id']].add(to_node['id'])
            
            # Issue 1: ALL descendants should ONLY connect from the latest Egyptian node
            # Remove ANY edge from earlier Egyptian nodes to dem/cop descendants
            # Then ensure all descendants connect from the latest node
            
            all_descendants = set()  # All dem/cop descendants in the network
            for edge in inherited_edges:
                from_node = next((n for n in network['nodes'] if n['id'] == edge['from']), None)
                to_node = next((n for n in network['nodes'] if n['id'] == edge['to']), None)
                
                if from_node and to_node:
                    if from_node['language'] == 'egy' and to_node['language'] in ['dem', 'cop']:
                        all_descendants.add(to_node['id'])
                        
                        # Remove if from ANY node except the latest
                        if from_node['id'] != latest_egy_node['id']:
                            edges_to_remove.append(edge)
                            removed_count += 1
            
            # Now ensure all descendants connect from latest node
            latest_descendants = egy_to_descendants.get(latest_egy_node['id'], set())
            for desc_id in all_descendants:
                if desc_id not in latest_descendants:
                    # Add missing edge from latest to this descendant
                    desc_node = next(n for n in network['nodes'] if n['id'] == desc_id)
                    edge = self.create_edge(
                        from_id=latest_egy_node['id'],
                        to_id=desc_id,
                        edge_type='INHERITED',
                        notes=f'Egy → {desc_node["language"].title()}'
                    )
                    network['edges'].append(edge)
            
            # Issue 2: Remove direct Egyptian→Coptic if there's Egyptian→Demotic→Coptic path
            # Re-capture INHERITED edges after adding new ones from latest node
            inherited_edges = [e for e in network['edges'] if e['type'] == 'INHERITED']
            
            # Rebuild the egy_to_descendants map with the updated edges
            egy_to_descendants = {}
            for edge in inherited_edges:
                from_node = next((n for n in network['nodes'] if n['id'] == edge['from']), None)
                to_node = next((n for n in network['nodes'] if n['id'] == edge['to']), None)
                
                if from_node and to_node and from_node['language'] == 'egy':
                    if from_node['id'] not in egy_to_descendants:
                        egy_to_descendants[from_node['id']] = set()
                    egy_to_descendants[from_node['id']].add(to_node['id'])
            
            # Build a map of Demotic→Coptic edges
            dem_to_cop = {}  # dem_id -> set of cop_ids
            for edge in inherited_edges:
                from_node = next((n for n in network['nodes'] if n['id'] == edge['from']), None)
                to_node = next((n for n in network['nodes'] if n['id'] == edge['to']), None)
                
                if from_node and to_node and from_node['language'] == 'dem' and to_node['language'] == 'cop':
                    if from_node['id'] not in dem_to_cop:
                        dem_to_cop[from_node['id']] = set()
                    dem_to_cop[from_node['id']].add(to_node['id'])
            
            # Find which Coptic nodes are reachable via Demotic
            coptic_via_demotic = set()
            for egy_id, dem_ids in egy_to_descendants.items():
                for dem_id in dem_ids:
                    dem_node = next((n for n in network['nodes'] if n['id'] == dem_id), None)
                    if dem_node and dem_node['language'] == 'dem':
                        # Get Coptic descendants of this Demotic node
                        cop_ids = dem_to_cop.get(dem_id, set())
                        coptic_via_demotic.update(cop_ids)
            
            # Remove direct Egyptian→Coptic edges if Coptic is reachable via Demotic
            for edge in inherited_edges:
                if edge in edges_to_remove:
                    continue  # Already marked for removal
                
                from_node = next((n for n in network['nodes'] if n['id'] == edge['from']), None)
                to_node = next((n for n in network['nodes'] if n['id'] == edge['to']), None)
                
                if from_node and to_node:
                    if from_node['language'] == 'egy' and to_node['language'] == 'cop':
                        if to_node['id'] in coptic_via_demotic:
                            edges_to_remove.append(edge)
                            removed_count += 1
            
            # Remove the edges
            for edge in edges_to_remove:
                network['edges'].remove(edge)
        
        return removed_count
    
    def find_egyptian_network(self, networks, lemma_form, etym_idx=None):
        """Find the Egyptian network for a given lemma and etymology"""
        for network in networks:
            if (network['root_language'] == 'egy' and 
                network['root_lemma'] == lemma_form):
                if etym_idx is None or network['root_etymology_index'] == etym_idx:
                    return network
        return None
    
    def find_best_ancestor_match(self, nodes, ancestor_form, descendant_pos, descendant_meanings):
        """
        Find the best matching Egyptian ancestor node for a descendant.
        Prefers POS match, then falls back to any matching form.
        
        This handles cases where one Egyptian etymology has multiple POS variants
        (e.g., verb/adj/noun wꜥb) and descendants should attach to the right one.
        """
        # Filter to Egyptian nodes with matching form
        egy_nodes = [n for n in nodes if n['language'] == 'egy' and n['form'] == ancestor_form]
        
        if not egy_nodes:
            return None
        
        # If only one match, use it
        if len(egy_nodes) == 1:
            return egy_nodes[0]
        
        # Try to match by POS
        pos_matches = [n for n in egy_nodes if n.get('part_of_speech') == descendant_pos]
        if pos_matches:
            return pos_matches[0]
        
        # Try to match by meaning similarity (simple keyword match)
        if descendant_meanings:
            descendant_text = ' '.join(descendant_meanings).lower()
            best_match = None
            best_score = 0
            
            for node in egy_nodes:
                node_meanings = node.get('meanings', [])
                if node_meanings:
                    node_text = ' '.join(node_meanings).lower()
                    # Simple keyword overlap
                    common_words = set(descendant_text.split()) & set(node_text.split())
                    if len(common_words) > best_score:
                        best_score = len(common_words)
                        best_match = node
            
            if best_match:
                return best_match
        
        # Fall back to first match (prefer nodes without definition_index, i.e., older entries)
        return min(egy_nodes, key=lambda n: n.get('definition_index', 0))
    
    def add_demotic_descendants(self, egy_networks, egy_data, dem_data):
        """
        Add Demotic descendants to their Egyptian ancestor networks.
        Demotic words are added as LEAF nodes (no further expansion).
        """
        count = 0
        
        for lemma_form, entry in dem_data.items():
            etymologies = entry.get('etymologies', [])
            
            for etym_idx, etymology in enumerate(etymologies):
                # Look for Egyptian ancestor in etymology text
                egy_ancestor = self.extract_egyptian_ancestor(etymology.get('etymology_text', ''))
                
                if egy_ancestor:
                    # Find the Egyptian network to attach to
                    egy_network = self.find_egyptian_network(egy_networks, egy_ancestor)
                    
                    if egy_network:
                        # Add Demotic descendant as leaf node
                        for defn in etymology.get('definitions', []):
                            pos = defn.get('part_of_speech', 'unknown')
                            meanings = defn.get('definitions', [])
                            quotes = defn.get('quotes', [])
                            
                            # Check if this Demotic word already exists in the network
                            existing_dem = next((n for n in egy_network['nodes'] 
                                               if n['language'] == 'dem' and n['form'] == lemma_form), None)
                            
                            if existing_dem:
                                # Node exists - update meanings if they were empty
                                if not existing_dem.get('meanings'):
                                    existing_dem['meanings'] = meanings
                                # Update part_of_speech if it was unknown
                                if existing_dem.get('part_of_speech') in [None, 'unknown'] and pos not in [None, 'unknown']:
                                    existing_dem['part_of_speech'] = pos
                                # Set etymology_index if not already set
                                if existing_dem.get('etymology_index') is None:
                                    existing_dem['etymology_index'] = etym_idx
                                dem_node = existing_dem
                            else:
                                # Create new node
                                dem_node = self.create_node(
                                    language='dem',
                                    form=lemma_form,
                                    pos=pos,
                                    meanings=meanings, quotes=quotes,
                                    etymology_index=etym_idx
                                )
                                egy_network['nodes'].append(dem_node)
                                count += 1
                            
                            # Find the best matching Egyptian ancestor node
                            # Prefer matching by POS, then fall back to any Egyptian node with the form
                            egy_root = self.find_best_ancestor_match(
                                egy_network['nodes'],
                                egy_ancestor,
                                pos,
                                meanings
                            )
                            
                            if egy_root:
                                # Check if edge already exists
                                edge_exists = any(e['from'] == egy_root['id'] and e['to'] == dem_node['id'] 
                                                 for e in egy_network['edges'])
                                if not edge_exists:
                                    edge = self.create_edge(
                                        from_id=egy_root['id'],
                                        to_id=dem_node['id'],
                                        edge_type='INHERITED',
                                        notes='Egyptian → Demotic'
                                    )
                                    egy_network['edges'].append(edge)
        
        return count
    
    def extract_egyptian_ancestor(self, etym_text):
        """Extract Egyptian ancestor form from etymology text"""
        if not etym_text:
            return None
        
        # Look for {{inh|dem|egy|form}} or similar patterns
        match = re.search(r'\{\{(?:inh|der|bor)\|(?:dem|egx-dem)\|egy\|([^|}]+)', etym_text)
        if match:
            ancestor = match.group(1).strip()
            # Remove any HTML tags
            ancestor = re.sub(r'<[^>]+>', '', ancestor)
            return ancestor
        
        return None
    
    def add_coptic_descendants(self, egy_networks, egy_data, cop_data):
        """
        Add Coptic descendants to their Egyptian ancestor networks.
        Coptic words are added as LEAF nodes (no further expansion).
        """
        count = 0
        
        for lemma_form, entry in cop_data.items():
            etymologies = entry.get('etymologies', [])
            
            for etym_idx, etymology in enumerate(etymologies):
                # Look for Egyptian ancestor in etymology text
                egy_ancestor = self.extract_coptic_egyptian_ancestor(etymology.get('etymology_text', ''))
                
                if egy_ancestor:
                    # Find the Egyptian network to attach to
                    egy_network = self.find_egyptian_network(egy_networks, egy_ancestor)
                    
                    if egy_network:
                        # Add Coptic descendant as leaf node
                        for defn in etymology.get('definitions', []):
                            pos = defn.get('part_of_speech', 'unknown')
                            meanings = defn.get('definitions', [])
                            quotes = defn.get('quotes', [])
                            dialect = self.extract_coptic_dialect(lemma_form, defn)
                            
                            # Check if this Coptic word already exists in the network
                            existing_cop = next((n for n in egy_network['nodes'] 
                                               if n['language'] == 'cop' and n['form'] == lemma_form), None)
                            
                            if existing_cop:
                                # Node exists - update dialect and meanings
                                if dialect:
                                    self.add_dialect_to_node(existing_cop, dialect)
                                # Update meanings if they were empty
                                if not existing_cop.get('meanings'):
                                    existing_cop['meanings'] = meanings
                                # Update part_of_speech if it was unknown
                                if existing_cop.get('part_of_speech') in [None, 'unknown'] and pos not in [None, 'unknown']:
                                    existing_cop['part_of_speech'] = pos
                                # Set etymology_index if not already set
                                if existing_cop.get('etymology_index') is None:
                                    existing_cop['etymology_index'] = etym_idx
                                # Don't increment count or add new node
                                cop_node = existing_cop
                            else:
                                # Create new node
                                cop_node = self.create_node(
                                    language='cop',
                                    form=lemma_form,
                                    pos=pos,
                                    meanings=meanings, quotes=quotes,
                                    dialect=dialect,
                                    etymology_index=etym_idx
                                )
                                egy_network['nodes'].append(cop_node)
                                count += 1
                            
                            # Find the best matching Egyptian ancestor node
                            # Prefer matching by POS, then fall back to any Egyptian node with the form
                            egy_root = self.find_best_ancestor_match(
                                egy_network['nodes'],
                                egy_ancestor,
                                pos,
                                meanings
                            )
                            
                            if egy_root:
                                # Check if edge already exists
                                edge_exists = any(e['from'] == egy_root['id'] and e['to'] == cop_node['id'] 
                                                 for e in egy_network['edges'])
                                if not edge_exists:
                                    edge = self.create_edge(
                                        from_id=egy_root['id'],
                                        to_id=cop_node['id'],
                                        edge_type='INHERITED',
                                        notes='Egyptian → Coptic'
                                    )
                                    egy_network['edges'].append(edge)
        
        return count
    
    def extract_coptic_egyptian_ancestor(self, etym_text):
        """Extract Egyptian ancestor form from Coptic etymology text"""
        if not etym_text:
            return None
        
        # Look for {{inh|cop|egy|form}} or similar patterns
        match = re.search(r'\{\{(?:inh|der|bor)\|cop[^|]*\|egy\|([^|}]+)', etym_text)
        if match:
            ancestor = match.group(1).strip()
            # Remove any HTML tags
            ancestor = re.sub(r'<[^>]+>', '', ancestor)
            return ancestor
        
        return None
    
    def extract_coptic_dialect(self, lemma_form, defn):
        """Extract Coptic dialect from definition or parameters"""
        # Check parameters for dialect info
        params = defn.get('parameters', {})
        if 'dialect' in params:
            return params['dialect']
        
        # Common Coptic dialect abbreviations
        if any(d in lemma_form for d in ['ⲃ', 'ⲥ', 'ⲁ', 'ⲗ', 'ⲫ']):
            # Could detect based on Coptic letters, but this is complex
            pass
        
        return None
    
    def build_demotic_standalone_networks(self, dem_data, egy_data):
        """Build standalone networks for Demotic lemmas without Egyptian ancestors"""
        networks = []
        
        for lemma_form, entry in dem_data.items():
            etymologies = entry.get('etymologies', [])
            
            for etym_idx, etymology in enumerate(etymologies):
                # Check if this has an Egyptian ancestor
                egy_ancestor = self.extract_egyptian_ancestor(etymology.get('etymology_text', ''))
                
                # Only create standalone network if no Egyptian ancestor
                if not egy_ancestor:
                    network = {
                        'network_id': self.get_new_network_id(),
                        'root_lemma': lemma_form,
                        'root_language': 'dem',
                        'root_etymology_index': etym_idx,
                        'nodes': [],
                        'edges': []
                    }
                    
                    for defn in etymology.get('definitions', []):
                        pos = defn.get('part_of_speech', 'unknown')
                        meanings = defn.get('definitions', [])
                        quotes = defn.get('quotes', [])
                        
                        dem_node = self.create_node(
                            language='dem',
                            form=lemma_form,
                            pos=pos,
                            meanings=meanings, quotes=quotes
                        )
                        network['nodes'].append(dem_node)
                    
                    if network['nodes']:
                        networks.append(network)
        
        return networks
    
    def build_coptic_standalone_networks(self, cop_data, egy_data, dem_data):
        """Build standalone networks for Coptic lemmas without Egyptian ancestors"""
        networks = []
        
        for lemma_form, entry in cop_data.items():
            etymologies = entry.get('etymologies', [])
            
            for etym_idx, etymology in enumerate(etymologies):
                # Check if this has an Egyptian ancestor
                egy_ancestor = self.extract_coptic_egyptian_ancestor(etymology.get('etymology_text', ''))
                
                # Only create standalone network if no Egyptian ancestor
                if not egy_ancestor:
                    network = {
                        'network_id': self.get_new_network_id(),
                        'root_lemma': lemma_form,
                        'root_language': 'cop',
                        'root_etymology_index': etym_idx,
                        'nodes': [],
                        'edges': []
                    }
                    
                    pos_main_nodes = []
                    
                    for defn in etymology.get('definitions', []):
                        pos = defn.get('part_of_speech', 'unknown')
                        meanings = defn.get('definitions', [])
                        quotes = defn.get('quotes', [])
                        dialect = self.extract_coptic_dialect(lemma_form, defn)
                        
                        cop_node = self.create_node(
                            language='cop',
                            form=lemma_form,
                            pos=pos,
                            meanings=meanings, quotes=quotes,
                            dialect=dialect,
                            etymology_index=etym_idx
                        )
                        network['nodes'].append(cop_node)
                        pos_main_nodes.append(cop_node)
                        
                        # Add alternative forms as dialect variants
                        alt_forms = defn.get('alternative_forms', [])
                        for alt in alt_forms:
                            alt_form = alt.get('form', '')
                            alt_dialect = alt.get('dialect', '')
                            
                            if not alt_form:
                                continue
                            
                            # Skip if this is just a dialect code (e.g., "OC", "S", "B")
                            # Dialect codes are 1-3 uppercase letters
                            if len(alt_form) <= 3 and alt_form.isupper():
                                continue
                            
                            # Check if this alt form already exists
                            existing_alt = next((n for n in network['nodes'] 
                                               if n['form'] == alt_form and n['language'] == 'cop'), None)
                            
                            if not existing_alt:
                                # Create variant node
                                alt_node = self.create_node(
                                    language='cop',
                                    form=alt_form,
                                    pos=pos,
                                    meanings=meanings, quotes=quotes,
                                    dialect=alt_dialect,
                                    etymology_index=etym_idx
                                )
                                network['nodes'].append(alt_node)
                                
                                # Create VARIANT edge
                                edge = self.create_edge(
                                    from_id=cop_node['id'],
                                    to_id=alt_node['id'],
                                    edge_type='VARIANT',
                                    notes=f'Dialectal variant ({alt_dialect})' if alt_dialect else 'Variant form'
                                )
                                network['edges'].append(edge)
                                
                                # Check if this alt form has its own entry with derived terms
                                if alt_form in cop_data:
                                    alt_entry = cop_data[alt_form]
                                    for alt_etym in alt_entry.get('etymologies', []):
                                        for alt_defn in alt_etym.get('definitions', []):
                                            # Add derived terms from the alt form's own entry
                                            for derived_form in alt_defn.get('derived_terms', []):
                                                if not derived_form or derived_form == alt_form:
                                                    continue
                                                
                                                # Check if already added
                                                existing_derived = next((n for n in network['nodes']
                                                                       if n['form'] == derived_form and n['language'] == 'cop'), None)
                                                
                                                if not existing_derived:
                                                    # Create derived term node
                                                    derived_node = self.create_node(
                                                        language='cop',
                                                        form=derived_form,
                                                        pos='unknown',
                                                        meanings=[f'Derived from {alt_form}'],
                                                        dialect=None,
                                                        etymology_index=etym_idx
                                                    )
                                                    network['nodes'].append(derived_node)
                                                    
                                                    # Create DERIVED edge from alt form to derived term
                                                    edge = self.create_edge(
                                                        from_id=alt_node['id'],
                                                        to_id=derived_node['id'],
                                                        edge_type='DERIVED',
                                                        notes=f'Derived from {alt_form}'
                                                    )
                                                    network['edges'].append(edge)
                            else:
                                # Node exists - just add dialect if needed
                                if alt_dialect:
                                    self.add_dialect_to_node(existing_alt, alt_dialect)
                                
                                # Create edge if it doesn't exist
                                edge_exists = any(e['from'] == cop_node['id'] and e['to'] == existing_alt['id'] 
                                                for e in network['edges'])
                                if not edge_exists:
                                    edge = self.create_edge(
                                        from_id=cop_node['id'],
                                        to_id=existing_alt['id'],
                                        edge_type='VARIANT',
                                        notes=f'Dialectal variant ({alt_dialect})' if alt_dialect else 'Variant form'
                                    )
                                    network['edges'].append(edge)
                    
                    # Process etymology components for Coptic compound words
                    # NOTE: Skip components that are actually etymological sources (mentioned in templates)
                    etymology_components = etymology.get('etymology_components', [])
                    etymology_text = etymology.get('etymology_text', '')
                    
                    if etymology_components and pos_main_nodes:
                        # Use the first main node as the compound word node
                        compound_node = pos_main_nodes[0]
                        
                        for component in etymology_components:
                            component_form = component.get('form', '')
                            component_lang = component.get('language', 'cop')  # Use component's language
                            
                            if not component_form or component_form == lemma_form:
                                continue
                            
                            # Skip if this component appears in etymology templates (it's an etymological source, not a compound part)
                            # Check for {{m|...|component_form...}}, {{inh|...|component_form...}}, etc.
                            etymology_template_pattern = r'\{\{(?:m|l|inh|bor|der)\|[^}]*?' + re.escape(component_form) + r'[^}]*?\}\}'
                            if re.search(etymology_template_pattern, etymology_text):
                                # This is an etymological source, not a compound component
                                continue
                            
                            # Normalize language codes
                            lang_map = {
                                'egx-dem': 'dem',
                                'cop-akh': 'cop', 'cop-sah': 'cop', 'cop-boh': 'cop',
                                'cop-fay': 'cop', 'cop-lyc': 'cop', 'cop-oxy': 'cop'
                            }
                            standard_lang = lang_map.get(component_lang, component_lang)
                            
                            # Check if we already have this component in the current network
                            existing_component = next((n for n in network['nodes'] 
                                                      if n['language'] == standard_lang and n['form'] == component_form), None)
                            
                            if not existing_component:
                                # Create stub node for component
                                component_node = self.create_node(
                                    language=standard_lang,
                                    form=component_form,
                                    pos='unknown',
                                    meanings=[f'Component of {lemma_form}'],
                                    dialect=None
                                )
                                network['nodes'].append(component_node)
                            else:
                                component_node = existing_component
                            
                            # Create COMPONENT edge from component to compound
                            edge = self.create_edge(
                                from_id=component_node['id'],
                                to_id=compound_node['id'],
                                edge_type='COMPONENT',
                                notes=f'Component of compound word'
                            )
                            network['edges'].append(edge)
                    
                    # Process etymology chain from etymology text
                    # Parse "from X, from Y, from Z" to create proper chain: Z → Y → X → current
                    etymology_text = etymology.get('etymology_text', '')
                    if etymology_text and pos_main_nodes:
                        target_node = pos_main_nodes[0]
                        
                        # Parse etymology chain
                        chain = self.parse_etymology_chain(etymology_text)
                        
                        # Normalize language codes
                        lang_map = {
                            'egx-dem': 'dem',
                            'cop-akh': 'cop', 'cop-sah': 'cop', 'cop-boh': 'cop',
                            'cop-fay': 'cop', 'cop-lyc': 'cop', 'cop-oxy': 'cop'
                        }
                        
                        # Create nodes for chain items
                        chain_nodes = []
                        for item in chain:
                            item_lang = lang_map.get(item['language'], item['language'])
                            item_form = item['form']
                            item_gloss = item['gloss']
                            item_type = item['type']
                            
                            if not item_form or not item_lang:
                                continue
                            
                            # Check if node already exists
                            existing_node = next((n for n in network['nodes']
                                                if n['language'] == item_lang and n['form'] == item_form), None)
                            
                            if not existing_node:
                                # Create node
                                meanings = [item_gloss] if item_gloss else []
                                
                                # If no gloss and Egyptian-family, infer from target
                                if not meanings and item_lang in ['egy', 'dem', 'cop']:
                                    target_meanings = target_node.get('meanings', [])
                                    if target_meanings:
                                        meanings = [f"Earlier form; cf. {target_meanings[0][:50]}"]
                                
                                node = self.create_node(
                                    language=item_lang,
                                    form=item_form,
                                    pos='unknown',
                                    meanings=meanings, quotes=quotes,
                                    dialect=None
                                )
                                network['nodes'].append(node)
                                chain_nodes.append({'node': node, 'type': item_type})
                            else:
                                # Add gloss if not already there
                                if item_gloss and item_gloss not in existing_node.get('meanings', []):
                                    if 'meanings' not in existing_node:
                                        existing_node['meanings'] = []
                                    existing_node['meanings'].append(item_gloss)
                                chain_nodes.append({'node': existing_node, 'type': item_type})
                        
                        # Create chain edges: oldest → ... → newest → target
                        # chain is already ordered oldest to newest
                        for i in range(len(chain_nodes)):
                            if i < len(chain_nodes) - 1:
                                # Link to next in chain
                                from_node = chain_nodes[i]['node']
                                to_node = chain_nodes[i + 1]['node']
                                item_type = chain_nodes[i + 1]['type']
                            else:
                                # Link last chain item to target
                                from_node = chain_nodes[i]['node']
                                to_node = target_node
                                item_type = chain_nodes[i]['type']
                            
                            # Check if edge already exists
                            edge_exists = any(e['from'] == from_node['id'] and e['to'] == to_node['id']
                                            for e in network['edges'])
                            if edge_exists:
                                continue
                            
                            # Determine edge type
                            from_lang = from_node['language']
                            to_lang = to_node['language']
                            
                            if item_type == 'inh':
                                edge_type = 'INHERITED'
                            elif item_type == 'bor':
                                edge_type = 'BORROWED'
                            elif item_type == 'der':
                                edge_type = 'DERIVED'
                            else:
                                # {{m}} or {{l}} - use INHERITED for cross-language, VARIANT for same-language
                                if from_lang != to_lang:
                                    edge_type = 'INHERITED'
                                else:
                                    edge_type = 'VARIANT'
                            
                            edge = self.create_edge(
                                from_id=from_node['id'],
                                to_id=to_node['id'],
                                edge_type=edge_type,
                                notes=f'{from_lang.title()} → {to_lang.title()}'
                            )
                            network['edges'].append(edge)
                    
                    if network['nodes']:
                        networks.append(network)
        
        return networks
    
    def export_networks(self, output_file):
        """Export networks to JSON file"""
        print(f"\nExporting {len(self.networks)} networks to {output_file}...")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.networks, f, ensure_ascii=False, indent=2)
        
        # Print statistics
        total_nodes = sum(len(net['nodes']) for net in self.networks)
        total_edges = sum(len(net['edges']) for net in self.networks)
        
        print(f"Export complete!")
        print(f"  Total networks: {len(self.networks)}")
        print(f"  Total nodes: {total_nodes}")
        print(f"  Total edges: {total_edges}")
        print(f"  Average nodes per network: {total_nodes/len(self.networks):.1f}")
        print(f"  Average edges per network: {total_edges/len(self.networks):.1f}")


def main():
    print("Lemma Network Builder V2 - Ego-centric Approach")
    print("="*80)
    print()
    
    print("Loading parsed Wiktionary data...")
    
    with open('egyptian_lemmas_parsed_mwp.json', 'r', encoding='utf-8') as f:
        egy_data = json.load(f)
    
    with open('demotic_lemmas_parsed_mwp.json', 'r', encoding='utf-8') as f:
        dem_data = json.load(f)
    
    with open('coptic_lemmas_parsed_mwp.json', 'r', encoding='utf-8') as f:
        cop_data = json.load(f)
    
    print(f"Loaded {len(egy_data)} Egyptian, {len(dem_data)} Demotic, {len(cop_data)} Coptic lemmas")
    
    # Build networks
    builder = EgocentricLemmaNetworkBuilder()
    networks = builder.build_networks_from_parsed_data(egy_data, dem_data, cop_data)
    
    # Export
    builder.export_networks('lemma_networks_v2.json')
    
    print("\n" + "="*80)
    print("Network building complete!")
    print("\nThe output file 'lemma_networks_v2.json' contains:")
    print("- Each network is ego-centric, focused on ONE lemma")
    print("- Nodes: the lemma, its variants, and direct descendants (as leaf nodes)")
    print("- Edges: VARIANT (spelling/hieroglyphic), DESCENDS (cross-language)")
    print("\nThis can be used to visualize individual lemma evolution without sprawl.")


if __name__ == '__main__':
    main()
