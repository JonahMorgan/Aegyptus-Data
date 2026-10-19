"""
Lemma Network Builder for Egyptian Language Evolution

This script builds temporal networks showing how Egyptian words evolved across time:
- Egyptian (Old Kingdom ~2686 BCE → Greco-Roman Period ~395 CE)
- Demotic (~650 BCE → ~452 CE)
- Coptic (~200 CE → ~1300 CE, still used liturgically)

Key Design Decisions:
1. LEMMA UNIFICATION: Alternative forms are treated as the same lemma
   - Egyptian alt forms with different dates → same lemma in different periods
   - Coptic alt forms with different dialects → same lemma in different regions
   
2. TEMPORAL TRACKING: Five types of relationships
   - EVOLVES: Same language, different time period (via dated alt forms)
   - DESCENDS: Cross-language inheritance (Egyptian → Demotic → Coptic)
   - VARIANT: Same time/language, different spelling (undated alt forms, dialects)
   - DERIVED: Derivational morphology (base word → derived term)
   - COMPONENT: Compositional morphology (morpheme → compound/affixed word)

3. NETWORK STRUCTURE: Graph-based representation
   - Nodes: {lemma, language, period/dialect, part_of_speech, meaning}
   - Edges: {relationship_type, confidence, notes}

Output: JSON with lemma networks suitable for training a temporal translation model
"""

import json
import re
from collections import defaultdict
import sys

sys.stdout.reconfigure(encoding='utf-8')

class LemmaNetworkBuilder:
    def __init__(self):
        self.networks = {}  # lemma_id -> network graph
        self.lemma_index = {}  # (language, form) -> lemma_id
        self.next_id = 0
        
        # Time period ordering (approximate)
        self.egyptian_periods = [
            'Old Kingdom', 'First Intermediate Period', 'Middle Kingdom',
            'Second Intermediate Period', 'New Kingdom', 'Third Intermediate Period',
            'Late Period', 'Ptolemaic Period', 'Greco-Roman Period',
            'Pyramid Texts', 'Coffin Texts', 'Book of the Dead'
        ]
        
    def get_or_create_node_id(self, language, form, period=None, dialect=None, hieroglyphs=None, etymology_index=None):
        """Get existing node ID or create new one"""
        # Include hieroglyphs AND etymology_index to distinguish:
        # - variants with same transliteration but different glyphs
        # - different etymologies of the same form (e.g., mwt = "mother" vs "to die")
        key = (language, form, period or '', dialect or '', hieroglyphs or '', etymology_index if etymology_index is not None else '')
        if key not in self.lemma_index:
            self.lemma_index[key] = f"L{self.next_id:05d}"
            self.next_id += 1
        return self.lemma_index[key]
    
    def create_node(self, node_id, language, form, part_of_speech, meanings, 
                    period=None, dialect=None, hieroglyphs=None, transliteration=None, etymology_index=None):
        """Create a node in the network"""
        node = {
            'id': node_id,
            'language': language,
            'form': form,
            'transliteration': transliteration,
            'hieroglyphs': hieroglyphs,
            'part_of_speech': part_of_speech,
            'meanings': meanings,
            'period': period,
            'dialect': dialect
        }
        if etymology_index is not None:
            node['etymology_index'] = etymology_index
        return node
    
    def extract_period_from_date(self, date_str):
        """Extract standardized period from date string"""
        if not date_str:
            return None
        
        # Check for known periods
        for period in self.egyptian_periods:
            if period.lower() in date_str.lower():
                return period
        
        # Extract dynasty numbers
        dynasty_match = re.search(r'(\d+)(?:st|nd|rd|th)\s+Dynasty', date_str)
        if dynasty_match:
            return f"{dynasty_match.group(1)}th Dynasty"
        
        return date_str  # Return as-is if we can't standardize
    
    def get_period_rank(self, period):
        """Get chronological ranking of a period (lower = earlier)"""
        if not period:
            return 999
        
        # Textual periods
        period_rankings = {
            'Pyramid Texts': 1,
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
            'Ptolemaic Period': 9,
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
            if dynasty_num <= 6:
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
    
    def parse_etymology_for_ancestor(self, etymology_text, current_lang):
        """Extract ancestor language and form from etymology text"""
        # Pattern: {{inh|current_lang|ancestor_lang|ancestor_form|...}}
        pattern = r'\{\{inh\|' + re.escape(current_lang) + r'\|([^|]+)\|([^|}\s]+)'
        match = re.search(pattern, etymology_text)
        
        if match:
            ancestor_lang = match.group(1).strip()
            ancestor_form = match.group(2).strip()
            # Remove HTML/hieroglyphs
            ancestor_form = re.sub(r'<hiero>.*?</hiero>', '', ancestor_form)
            return ancestor_lang, ancestor_form
        
        # Also check for {{m|lang|form}} patterns
        pattern2 = r'\{\{m\|([^|]+)\|([^|}\s]+)'
        match2 = re.search(pattern2, etymology_text)
        if match2:
            return match2.group(1).strip(), match2.group(2).strip()
        
        return None, None
    
    def parse_alternative_form_of(self, definitions):
        """
        Extract 'alternative form of' references from definitions.
        Returns (language, form) tuple if found, otherwise (None, None).
        
        Patterns to detect:
        - "Alternative form of X"
        - "[dialect] Alternative form of X"
        - In parsed definitions like: "[B] Alternative form of ⲟⲩⲟϣⲟⲩⲉϣ"
        """
        if not definitions:
            return None, None
        
        for defn in definitions:
            # Pattern: [dialect] Alternative form of <form>
            # or just: Alternative form of <form>
            pattern = r'(?:\[[^\]]+\]\s*)?[Aa]lternative form of\s+(.+?)(?:\s|$)'
            match = re.search(pattern, defn)
            
            if match:
                target_form = match.group(1).strip()
                # Remove any trailing punctuation or markup
                target_form = re.sub(r'[.,;!?]$', '', target_form)
                target_form = re.sub(r'\{\{.*?\}\}', '', target_form).strip()
                
                # For now, assume same language (will be refined per language processing)
                return None, target_form  # Language will be set by caller
        
        return None, None
    
    def build_networks_from_parsed_data(self, egy_data, dem_data, cop_data):
        """Build lemma networks from all three language datasets"""
        
        print("Building lemma networks...")
        print("="*80)
        
        # Process Egyptian lemmas
        print("\n1. Processing Egyptian lemmas...")
        egy_count = self.process_egyptian_lemmas(egy_data)
        print(f"   Created {egy_count} Egyptian nodes")
        
        # Process Demotic lemmas (with links to Egyptian)
        print("\n2. Processing Demotic lemmas...")
        dem_count = self.process_demotic_lemmas(dem_data, egy_data)
        print(f"   Created {dem_count} Demotic nodes")
        
        # Process Coptic lemmas (with links to Demotic and Egyptian)
        print("\n3. Processing Coptic lemmas...")
        cop_count = self.process_coptic_lemmas(cop_data, dem_data, egy_data)
        print(f"   Created {cop_count} Coptic nodes")
        
        # Merge networks for "alternative form of" references that were processed in wrong order
        print("\n4. Merging alternative form networks...")
        merged_count = self.merge_alternative_form_networks()
        print(f"   Merged {merged_count} alternative form networks")
        
        # Cleanup: Remove direct Egyptian→Coptic edges when Demotic descendant exists
        print("\n5. Cleaning up routing (removing direct Egyptian→Coptic edges where Demotic exists)...")
        removed_edges = self.cleanup_coptic_routing()
        print(f"   Removed {removed_edges} direct Egyptian→Coptic edges")
        
        print(f"\nTotal networks created: {len(self.networks)}")
        return self.networks
    
    def process_egyptian_lemmas(self, egy_data):
        """Process Egyptian lemmas with temporal evolution via alternative forms"""
        node_count = 0
        
        for lemma_form, entry in egy_data.items():
            for etym_idx, etym in enumerate(entry.get('etymologies', [])):
                for defn in etym.get('definitions', []):
                    pos = defn.get('part_of_speech', 'unknown')
                    meanings = defn.get('definitions', [])
                    
                    # Check if this is an "alternative form of" another Egyptian lemma
                    _, alt_form_target = self.parse_alternative_form_of(meanings)
                    
                    # If this is an alternative form, try to merge into target's network
                    if alt_form_target:
                        target_id = self.get_or_create_node_id('egy', alt_form_target, etymology_index=etym_idx)
                        
                        # Create target network if it doesn't exist (placeholder for forward reference)
                        if target_id not in self.networks:
                            target_node = self.create_node(target_id, 'egy', alt_form_target, pos, [])
                            self.networks[target_id] = {
                                'root_node': target_node,
                                'nodes': [target_node],
                                'edges': [],
                                'has_demotic_descendant': False
                            }
                            node_count += 1
                        
                        network = self.networks[target_id]
                        
                        # Create node for this alternative form
                        alt_id = self.get_or_create_node_id('egy', lemma_form, etymology_index=etym_idx)
                        alt_node = self.create_node(alt_id, 'egy', lemma_form, pos, meanings, etymology_index=etym_idx)
                        
                        # Add node if not already present
                        if not any(n['id'] == alt_id for n in network['nodes']):
                            network['nodes'].append(alt_node)
                            node_count += 1
                        
                        # Create VARIANT edge from target to this form
                        edge_exists = any(e.get('from') == target_id and e.get('to') == alt_id 
                                        for e in network['edges'])
                        if not edge_exists:
                            edge = {
                                'from': target_id,
                                'to': alt_id,
                                'type': 'VARIANT',
                                'notes': f'Alternative form of {alt_form_target}'
                            }
                            network['edges'].append(edge)
                        
                        # Skip normal processing for this entry
                        continue
                    
                    # Collect all forms (main + alternatives), separating by inflection
                    # Key: (inflection_type, base_form) - e.g., ('plural', 'jꜥnw') or ('singular', '')
                    forms_by_inflection = {}
                    
                    # Main lemma form (singular/base form)
                    main_id = self.get_or_create_node_id('egy', lemma_form, etymology_index=etym_idx)
                    main_node = self.create_node(
                        main_id, 'egy', lemma_form, pos, meanings, etymology_index=etym_idx
                    )
                    
                    inflection_key = ('base', '')
                    if inflection_key not in forms_by_inflection:
                        forms_by_inflection[inflection_key] = []
                    
                    forms_by_inflection[inflection_key].append({
                        'id': main_id,
                        'node': main_node,
                        'period': None,
                        'period_rank': 999  # Undated = lowest priority
                    })
                    
                    # Alternative forms - check if they're inflections (plural, dual, etc.)
                    for alt_form in defn.get('alternative_forms', []):
                        alt_hieroglyphs = alt_form.get('hieroglyphs')
                        # Alternative forms typically don't have a separate transliteration
                        # They use the main lemma's transliteration (same word, different writing)
                        alt_translit = alt_form.get('transliteration') or alt_form.get('form') or lemma_form
                        period = self.extract_period_from_date(alt_form.get('date'))
                        title = alt_form.get('title', '')
                        note = alt_form.get('note', '')
                        
                        # Detect inflection type from title/note
                        inflection_info = f"{title} {note}".lower()
                        inflection_type = 'base'
                        inflection_form = ''
                        
                        if 'plural' in inflection_info or 'pl.' in inflection_info:
                            inflection_type = 'plural'
                            # Try to extract the plural form from title
                            # Pattern: "writings of plural {{m-self|egy|lemma|plural_form}}"
                            import re
                            plural_match = re.search(r'\{\{m-self\|egy\|[^|]+\|([^}]+)\}\}', title)
                            if plural_match:
                                inflection_form = plural_match.group(1)
                            else:
                                inflection_form = alt_translit
                        elif 'dual' in inflection_info:
                            inflection_type = 'dual'
                            inflection_form = alt_translit
                        elif 'feminine' in inflection_info or 'fem.' in inflection_info:
                            inflection_type = 'feminine'
                            inflection_form = alt_translit
                        
                        inflection_key = (inflection_type, inflection_form)
                        
                        alt_id = self.get_or_create_node_id('egy', alt_translit, period=period, hieroglyphs=alt_hieroglyphs, etymology_index=etym_idx)
                        alt_node = self.create_node(
                            alt_id, 'egy', alt_translit, pos, meanings,
                            period=period,
                            hieroglyphs=alt_hieroglyphs,
                            transliteration=alt_translit,
                            etymology_index=etym_idx
                        )
                        
                        # Get period rank for sorting
                        period_rank = self.get_period_rank(period) if period else 999
                        
                        if inflection_key not in forms_by_inflection:
                            forms_by_inflection[inflection_key] = []
                        
                        forms_by_inflection[inflection_key].append({
                            'id': alt_id,
                            'node': alt_node,
                            'period': period,
                            'period_rank': period_rank,
                            'note': note,
                            'title': title
                        })
                    
                    # Process alternative forms from definitions (new field from parser)
                    # These are simple variant forms extracted from "Alternative form of X" in definitions
                    for alt_from_def in defn.get('alternative_forms_from_definitions', []):
                        variant_form = alt_from_def.get('form')
                        if variant_form:
                            # Create edge to the variant (this lemma is alternative of variant_form)
                            variant_id = self.get_or_create_node_id('egy', variant_form, etymology_index=etym_idx)
                            
                            # Try to add to target network if it exists
                            if variant_id in self.networks:
                                network = self.networks[variant_id]
                                
                                # Add this lemma as a variant node
                                alt_id = self.get_or_create_node_id('egy', lemma_form, etymology_index=etym_idx)
                                alt_node = self.create_node(alt_id, 'egy', lemma_form, pos, meanings, etymology_index=etym_idx)
                                
                                if not any(n['id'] == alt_id for n in network['nodes']):
                                    network['nodes'].append(alt_node)
                                    node_count += 1
                                
                                # Create VARIANT edge from variant_form to this lemma
                                edge_exists = any(e.get('from') == variant_id and e.get('to') == alt_id 
                                                for e in network['edges'])
                                if not edge_exists:
                                    edge = {
                                        'from': variant_id,
                                        'to': alt_id,
                                        'type': 'VARIANT',
                                        'notes': f'Alternative form of {variant_form} (from definition)'
                                    }
                                    network['edges'].append(edge)
                    
                    # Create separate networks for each inflection type
                    for (inflection_type, inflection_form), all_forms in forms_by_inflection.items():
                        # Determine network ID based on inflection
                        if inflection_type == 'base':
                            network_id = main_id
                            network_label = lemma_form
                        else:
                            # For inflections, use the inflection form as base
                            # Create a unique network ID for this inflection
                            inflection_base = inflection_form if inflection_form else f"{lemma_form}_{inflection_type}"
                            network_id = self.get_or_create_node_id('egy', inflection_base, dialect=inflection_type, etymology_index=etym_idx)
                            network_label = f"{inflection_base} ({inflection_type})"
                        
                        # Find or create network
                        if network_id not in self.networks:
                            # Use main lemma form (undated) as root if available, otherwise earliest dated form
                            # The main lemma is always first in all_forms list (added before alternatives)
                            root_node = all_forms[0]['node']  # This is always the main lemma form
                            
                            self.networks[network_id] = {
                                'root_node': root_node,
                                'nodes': [],
                                'edges': [],
                                'has_demotic_descendant': False  # Track if Egyptian has Demotic descendant
                            }
                        
                        network = self.networks[network_id]
                        
                        # Add all nodes (avoiding duplicates)
                        for form_data in all_forms:
                            if not any(n['id'] == form_data['id'] for n in network['nodes']):
                                network['nodes'].append(form_data['node'])
                                node_count += 1
                        
                        # Create edges between dated forms
                        # Group forms by period to find temporal evolution
                        by_period = {}
                        for form_data in all_forms:
                            period_rank = form_data.get('period_rank', 999)
                            if period_rank not in by_period:
                                by_period[period_rank] = []
                            by_period[period_rank].append(form_data)
                        
                        # Get distinct periods in chronological order
                        sorted_periods = sorted(by_period.keys())
                        
                        # Connect undated root to earliest dated form (DESCENDS from lemma to first attestation)
                        undated_forms = by_period.get(999, [])
                        dated_periods = [p for p in sorted_periods if p < 500]
                        
                        if undated_forms and dated_periods:
                            # Connect root (undated main lemma) to earliest dated form
                            root_form = undated_forms[0]  # Main lemma (should be first)
                            earliest_period = dated_periods[0]
                            earliest_forms = by_period[earliest_period]
                            
                            if earliest_forms:
                                edge = {
                                    'from': root_form['id'],
                                    'to': earliest_forms[0]['id'],
                                    'type': 'DESCENDS',
                                    'notes': f"First attestation in {earliest_forms[0].get('period', 'dated period')}"
                                }
                                network['edges'].append(edge)
                        
                        # For EVOLVES edges: Connect chronologically consecutive alternative forms
                        # These represent temporal evolution of the same word (different writings over time)
                        for i in range(len(dated_periods) - 1):
                            current_period = dated_periods[i]
                            next_period = dated_periods[i + 1]
                            
                            current_forms = by_period[current_period]
                            next_forms = by_period[next_period]
                            
                            # Connect each form in current period to the first form in next period
                            # This creates a chain showing temporal evolution of alternative forms
                            for curr_form in current_forms:
                                # Connect to first form of next period
                                if next_forms:
                                    edge = {
                                        'from': curr_form['id'],
                                        'to': next_forms[0]['id'],
                                        'type': 'EVOLVES',
                                        'notes': f"Evolution from {curr_form.get('period', '?')} to {next_forms[0].get('period', '?')}"
                                    }
                                    network['edges'].append(edge)
                            
                            # If multiple forms exist in the next period, connect them as variants
                            if len(next_forms) > 1:
                                # Connect subsequent forms in the same period as VARIANT edges
                                for j in range(1, len(next_forms)):
                                    # Already handled by VARIANT logic below
                                    pass
                        
                        # Create VARIANT edges: Different forms in the same period
                        for period_rank, forms in by_period.items():
                            if len(forms) > 1:
                                # Group by transliteration within this period
                                by_translit_in_period = {}
                                for form_data in forms:
                                    translit = form_data['node']['form']
                                    if translit not in by_translit_in_period:
                                        by_translit_in_period[translit] = []
                                    by_translit_in_period[translit].append(form_data)
                                
                                # Connect different hieroglyphic writings of same transliteration (true variants)
                                for translit, translit_forms in by_translit_in_period.items():
                                    if len(translit_forms) > 1:
                                        # Connect all to first one as the canonical form
                                        canonical = translit_forms[0]
                                        for variant in translit_forms[1:]:
                                            # Skip self-loops
                                            if canonical['id'] == variant['id']:
                                                continue
                                            
                                            # Format period properly
                                            period_str = variant.get('period') or 'undated'
                                            
                                            edge = {
                                                'from': canonical['id'],
                                                'to': variant['id'],
                                                'type': 'VARIANT',
                                                'notes': f"Hieroglyphic variant ({period_str})"
                                            }
                                            network['edges'].append(edge)
                                
                                # Connect different transliterations in same period (spelling variants)
                                if len(by_translit_in_period) > 1:
                                    # Pick most common as canonical
                                    canonical_translit = max(by_translit_in_period.items(), key=lambda x: len(x[1]))[0]
                                    canonical_form = by_translit_in_period[canonical_translit][0]
                                    
                                    for translit, translit_forms in by_translit_in_period.items():
                                        if translit != canonical_translit:
                                            # Skip self-loops
                                            if canonical_form['id'] == translit_forms[0]['id']:
                                                continue
                                            
                                            # Format period properly
                                            period_str = translit_forms[0].get('period') or 'undated'
                                            
                                            edge = {
                                                'from': canonical_form['id'],
                                                'to': translit_forms[0]['id'],
                                                'type': 'VARIANT',
                                                'notes': f"Spelling variant ({period_str})"
                                            }
                                            network['edges'].append(edge)
                        
                        # Add descendants (to Demotic/Coptic) - only from base form network
                        if inflection_type == 'base':
                            # Determine which Egyptian node should be the parent for descendants
                            # Use the latest dated form if available, otherwise the main undated form
                            dated_periods = [p for p in sorted_periods if p < 500]
                            
                            if dated_periods:
                                # Get the latest (highest ranked) period
                                latest_period = dated_periods[-1]
                                latest_forms = by_period[latest_period]
                                # Use the first form from the latest period as the parent
                                parent_egy_id = latest_forms[0]['id']
                            else:
                                # No dated forms, use the main undated lemma
                                parent_egy_id = main_id
                            
                            for desc in defn.get('descendants', []):
                                desc_lang = desc.get('language')
                                desc_word = desc.get('word')
                                
                                if desc_lang and desc_word:
                                    # Map language codes
                                    if desc_lang == 'egx-dem':
                                        desc_lang_code = 'dem'
                                        # Mark that this Egyptian network has a Demotic descendant
                                        network['has_demotic_descendant'] = True
                                    elif desc_lang == 'cop':
                                        desc_lang_code = 'cop'
                                    else:
                                        desc_lang_code = desc_lang
                                    
                                    # Create placeholder descendant node WITHOUT etymology_index
                                    # We don't know which etymology of the descendant this corresponds to
                                    # The actual lemma processing will create properly indexed nodes
                                    desc_id = self.get_or_create_node_id(desc_lang_code, desc_word)
                                    
                                    # Add node to network if not already there
                                    if not any(n['id'] == desc_id for n in network['nodes']):
                                        desc_node = self.create_node(desc_id, desc_lang_code, desc_word, pos, [])
                                        network['nodes'].append(desc_node)
                                    
                                    # Create edge from latest Egyptian form (not root)
                                    # Note: Egyptian→Coptic edges will be rerouted through Demotic
                                    # in cleanup_coptic_routing() if Demotic exists
                                    edge = {
                                        'from': parent_egy_id,
                                        'to': desc_id,
                                        'type': 'DESCENDS',
                                        'target_language': desc_lang
                                    }
                                    network['edges'].append(edge)
                            
                            # Add etymology components (morphological composition: prefix/suffix/compound)
                            for component_info in etym.get('etymology_components', []):
                                component_form = component_info.get('form')
                                component_role = component_info.get('role', 'base')  # prefix, suffix, or base
                                template_type = component_info.get('template_type', 'compound')
                                component_lang = component_info.get('language', 'egy')  # Default to Egyptian
                                
                                if component_form and component_lang == 'egy':
                                    # For affix formations: create COMPONENT edges from morphemes to derived word
                                    # prefix + base → derived word
                                    # base + suffix → derived word
                                    if template_type in ['prefix', 'suffix', 'affix', 'af', 'confix']:
                                        # Create node for the component (prefix, suffix, or base)
                                        component_id = self.get_or_create_node_id('egy', component_form)
                                        component_node = self.create_node(
                                            component_id, 'egy', component_form, 'morpheme', []
                                        )
                                        
                                        if not any(n['id'] == component_id for n in network['nodes']):
                                            network['nodes'].append(component_node)
                                            node_count += 1
                                        
                                        # Create COMPONENT edge (component → derived word)
                                        # This represents: "component is part of main_id"
                                        edge = {
                                            'from': component_id,
                                            'to': main_id,
                                            'type': 'COMPONENT',
                                            'notes': f'{component_role}: {component_form}'
                                        }
                                        # Check if edge already exists
                                        if not any(e.get('from') == component_id and e.get('to') == main_id for e in network['edges']):
                                            network['edges'].append(edge)
                                    
                                    # For compounds: create COMPONENT edges from each component to compound
                                    elif template_type == 'compound':
                                        component_id = self.get_or_create_node_id('egy', component_form)
                                        component_node = self.create_node(
                                            component_id, 'egy', component_form, 'word', []
                                        )
                                        
                                        if not any(n['id'] == component_id for n in network['nodes']):
                                            network['nodes'].append(component_node)
                                            node_count += 1
                                        
                                        # Create COMPONENT edge (component → compound)
                                        edge = {
                                            'from': component_id,
                                            'to': main_id,
                                            'type': 'COMPONENT',
                                            'notes': f'compound component: {component_form}'
                                        }
                                        # Check if edge already exists
                                        if not any(e.get('from') == component_id and e.get('to') == main_id for e in network['edges']):
                                            network['edges'].append(edge)
        
        return node_count
    
    def process_demotic_lemmas(self, dem_data, egy_data):
        """Process Demotic lemmas with inheritance from Egyptian"""
        node_count = 0
        
        for lemma_form, entry in dem_data.items():
            for etym_idx, etym in enumerate(entry.get('etymologies', [])):
                etym_text = etym.get('etymology_text', '')
                
                # Find Egyptian ancestor
                ancestor_lang, ancestor_form = self.parse_etymology_for_ancestor(etym_text, 'egx-dem')
                
                definitions = etym.get('definitions', [])
                
                # If no definitions, we still need to create a node if there's an etymology
                # This handles cases like Determiners that have descendants but no formal definitions
                if not definitions:
                    definitions = [{'part_of_speech': 'unknown', 'definitions': [], 'descendants': []}]
                
                for defn in definitions:
                    pos = defn.get('part_of_speech', 'unknown')
                    meanings = defn.get('definitions', [])
                    
                    # Create Demotic node
                    dem_id = self.get_or_create_node_id('dem', lemma_form, etymology_index=etym_idx)
                    dem_node = self.create_node(dem_id, 'dem', lemma_form, pos, meanings, etymology_index=etym_idx)
                    
                    # Create a new network for this Demotic etymology
                    # Different etymologies of the same lemma should be in separate networks initially
                    # The merge step will combine them later if they share nodes
                    if dem_id not in self.networks:
                        self.networks[dem_id] = {
                            'root_node': dem_node,
                            'nodes': [dem_node],
                            'edges': [],
                            'has_demotic_descendant': False
                        }
                        network = self.networks[dem_id]
                        node_count += 1
                    else:
                        network = self.networks[dem_id]
                    
                    # If has Egyptian ancestor, add Egyptian node to this network and create edge
                    if ancestor_lang == 'egy' and ancestor_form:
                        # Try to find an existing Egyptian node (without etymology index since we don't know which Egyptian etymology)
                        egy_id = self.get_or_create_node_id('egy', ancestor_form)
                        
                        # Check if Egyptian node exists in any network
                        egy_node = None
                        for net in self.networks.values():
                            for n in net['nodes']:
                                if n['id'] == egy_id:
                                    egy_node = n
                                    break
                            if egy_node:
                                break
                        
                        # If not found, create placeholder Egyptian node
                        if not egy_node:
                            egy_node = self.create_node(egy_id, 'egy', ancestor_form, pos, [])
                        
                        # Add Egyptian node to current network if not already there
                        if not any(n['id'] == egy_id for n in network['nodes']):
                            network['nodes'].append(egy_node)
                        
                        # Mark that this network has a Demotic descendant
                        network['has_demotic_descendant'] = True
                        
                        # Find the latest Egyptian form in the network to connect from
                        # This should be the most recent dated Egyptian node
                        egy_nodes = [n for n in network['nodes'] if n['language'] == 'egy']
                        
                        # Find the node with the latest period (highest rank among dated forms)
                        latest_egy_node = None
                        latest_rank = -1
                        
                        for egy_node in egy_nodes:
                            period = egy_node.get('period')
                            if period:
                                rank = self.get_period_rank(period)
                                if rank < 500 and rank > latest_rank:  # Dated form (not undated 999)
                                    latest_rank = rank
                                    latest_egy_node = egy_node
                        
                        # If no dated forms found, use the first Egyptian node
                        if not latest_egy_node and egy_nodes:
                            latest_egy_node = egy_nodes[0]
                        elif not latest_egy_node:
                            # No Egyptian nodes found, use the one we just added
                            latest_egy_node = egy_node
                        
                        parent_egy_id = latest_egy_node['id']
                        
                        # Create inheritance edge from Egyptian to Demotic (check if already exists)
                        edge_exists = any(e.get('from') == parent_egy_id and e.get('to') == dem_id 
                                        for e in network['edges'])
                        if not edge_exists:
                            edge = {
                                'from': parent_egy_id,
                                'to': dem_id,
                                'type': 'DESCENDS',
                                'etymology_snippet': etym_text[:200]
                            }
                            network['edges'].append(edge)
                    
                    # Add descendants (to Coptic)
                    for desc in defn.get('descendants', []):
                        desc_lang = desc.get('language')
                        desc_word = desc.get('word')
                        
                        if desc_lang and desc_word:
                            if network:
                                # Map language codes
                                desc_lang_code = 'cop' if desc_lang == 'cop' else desc_lang
                                
                                # Create placeholder descendant node WITHOUT etymology_index
                                # We don't know which etymology of the descendant this corresponds to
                                desc_id = self.get_or_create_node_id(desc_lang_code, desc_word)
                                
                                # Add node to network if not already there
                                if not any(n['id'] == desc_id for n in network['nodes']):
                                    desc_node = self.create_node(desc_id, desc_lang_code, desc_word, pos, [])
                                    network['nodes'].append(desc_node)
                                
                                edge = {
                                    'from': dem_id,
                                    'to': desc_id,
                                    'type': 'DESCENDS',
                                    'target_language': desc_lang
                                }
                                network['edges'].append(edge)
        
        return node_count
    
    def process_coptic_lemmas(self, cop_data, dem_data, egy_data):
        """Process Coptic lemmas with dialectal variants and inheritance"""
        node_count = 0
        
        for lemma_form, entry in cop_data.items():
            for etym_idx, etym in enumerate(entry.get('etymologies', [])):
                etym_text = etym.get('etymology_text', '')
                
                # Find ancestor - prefer structured etymology_ancestors over text parsing
                ancestor_lang_dem = None
                ancestor_form_dem = None
                
                # First check structured etymology ancestors
                etym_ancestors = etym.get('etymology_ancestors', [])
                if etym_ancestors:
                    # Look for Demotic ancestor first
                    dem_ancestor = next((a for a in etym_ancestors if a.get('language') in ['egx-dem', 'dem']), None)
                    if dem_ancestor:
                        ancestor_lang_dem = 'egx-dem'
                        ancestor_form_dem = dem_ancestor.get('form')
                    else:
                        # Fall back to Egyptian ancestor
                        egy_ancestor = next((a for a in etym_ancestors if a.get('language') == 'egy'), None)
                        if egy_ancestor:
                            ancestor_lang_dem = 'egy'
                            ancestor_form_dem = egy_ancestor.get('form')
                        else:
                            # Fall back to ANY other ancestor (Greek, Latin, etc.)
                            other_ancestor = etym_ancestors[0] if etym_ancestors else None
                            if other_ancestor:
                                ancestor_lang_dem = other_ancestor.get('language')
                                ancestor_form_dem = other_ancestor.get('form')
                
                # Fall back to text parsing if no structured data
                if not ancestor_form_dem:
                    ancestor_lang_dem, ancestor_form_dem = self.parse_etymology_for_ancestor(etym_text, 'cop')
                
                for defn in etym.get('definitions', []):
                    pos = defn.get('part_of_speech', 'unknown')
                    meanings = defn.get('definitions', [])
                    
                    # Check if this is an "alternative form of" another Coptic lemma
                    _, alt_form_target = self.parse_alternative_form_of(meanings)
                    
                    # Create main Coptic node
                    cop_id = self.get_or_create_node_id('cop', lemma_form, etymology_index=etym_idx)
                    cop_node = self.create_node(cop_id, 'cop', lemma_form, pos, meanings, etymology_index=etym_idx)
                    
                    # Create a new network for this Coptic etymology
                    # Different etymologies of the same lemma should be in separate networks initially
                    # The merge step will combine them later if they share nodes
                    if cop_id not in self.networks:
                        self.networks[cop_id] = {
                            'root_node': cop_node,
                            'nodes': [cop_node],
                            'edges': [],
                            'has_demotic_descendant': False
                        }
                        network = self.networks[cop_id]
                        node_count += 1
                    else:
                        network = self.networks[cop_id]
                    
                    parent_id = None
                    
                    # If this is an alternative form of another Coptic word, find that network
                    if alt_form_target:
                        # Find the target Coptic lemma's network (try without etymology index first)
                        target_id = self.get_or_create_node_id('cop', alt_form_target)
                        
                        # Search for existing target node to link to
                        for net in self.networks.values():
                            target_node = next((n for n in net['nodes'] if n['id'] == target_id), None)
                            if target_node:
                                parent_id = target_id
                                # Add target node to current network if not already there
                                if not any(n['id'] == target_id for n in network['nodes']):
                                    network['nodes'].append(target_node)
                                break
                        
                        # If target not found, create placeholder
                        if not parent_id:
                            target_node = self.create_node(target_id, 'cop', alt_form_target, pos, [])
                            network['nodes'].append(target_node)
                            parent_id = target_id
                    
                    # If not an alternative form, add ancestor node to this network
                    elif ancestor_form_dem:
                        # Try Demotic ancestor first
                        if ancestor_lang_dem == 'egx-dem':
                            parent_id = self.get_or_create_node_id('dem', ancestor_form_dem)
                            
                            # Check if Demotic node exists in any network
                            parent_node = None
                            for net in self.networks.values():
                                parent_node = next((n for n in net['nodes'] if n['id'] == parent_id), None)
                                if parent_node:
                                    break
                            
                            # If not found, create placeholder Demotic node
                            if not parent_node:
                                parent_node = self.create_node(parent_id, 'dem', ancestor_form_dem, pos, [])
                            
                            # Add Demotic node to current network if not already there
                            if not any(n['id'] == parent_id for n in network['nodes']):
                                network['nodes'].append(parent_node)
                        
                        # Try Egyptian ancestor
                        elif ancestor_lang_dem == 'egy':
                            parent_id = self.get_or_create_node_id('egy', ancestor_form_dem)
                            
                            # Check if Egyptian node exists in any network
                            parent_node = None
                            for net in self.networks.values():
                                parent_node = next((n for n in net['nodes'] if n['id'] == parent_id), None)
                                if parent_node:
                                    break
                            
                            # If not found, create placeholder Egyptian node
                            if not parent_node:
                                parent_node = self.create_node(parent_id, 'egy', ancestor_form_dem, pos, [])
                            
                            # Add Egyptian node to current network if not already there
                            if not any(n['id'] == parent_id for n in network['nodes']):
                                network['nodes'].append(parent_node)
                        
                        # Handle any other language (Greek, Latin, etc.)
                        else:
                            parent_id = self.get_or_create_node_id(ancestor_lang_dem, ancestor_form_dem)
                            
                            # Check if ancestor node exists in any network
                            parent_node = None
                            for net in self.networks.values():
                                parent_node = next((n for n in net['nodes'] if n['id'] == parent_id), None)
                                if parent_node:
                                    break
                            
                            # If not found, create placeholder node
                            if not parent_node:
                                parent_node = self.create_node(parent_id, ancestor_lang_dem, ancestor_form_dem, pos, [])
                            
                            # Add ancestor node to current network if not already there
                            if not any(n['id'] == parent_id for n in network['nodes']):
                                network['nodes'].append(parent_node)
                    
                    # Create inheritance edge if has parent
                    if parent_id:
                        # Check if edge already exists
                        edge_exists = any(e.get('from') == parent_id and e.get('to') == cop_id 
                                        for e in network['edges'])
                        if not edge_exists:
                            # Determine edge type based on relationship
                            if alt_form_target:
                                # Alternative form = VARIANT edge
                                edge = {
                                    'from': parent_id,
                                    'to': cop_id,
                                    'type': 'VARIANT',
                                    'notes': f'Alternative form of {alt_form_target}'
                                }
                            else:
                                # Cross-language inheritance = DESCENDS edge
                                edge = {
                                    'from': parent_id,
                                    'to': cop_id,
                                    'type': 'DESCENDS',
                                    'etymology_snippet': etym_text[:200]
                                }
                            network['edges'].append(edge)
                    
                    # Add dialectal variants
                    for alt_form in defn.get('alternative_forms', []):
                        alt_form_text = alt_form.get('form')
                        dialect = alt_form.get('dialect')
                        
                        if alt_form_text:
                            alt_id = self.get_or_create_node_id('cop', alt_form_text, dialect=dialect, etymology_index=etym_idx)
                            alt_node = self.create_node(
                                alt_id, 'cop', alt_form_text, pos, meanings,
                                dialect=dialect, etymology_index=etym_idx
                            )
                            
                            if not any(n['id'] == alt_id for n in network['nodes']):
                                network['nodes'].append(alt_node)
                                node_count += 1
                            
                            # Create variant edge
                            edge = {
                                'from': cop_id,
                                'to': alt_id,
                                'type': 'VARIANT',
                                'dialect': dialect
                            }
                            network['edges'].append(edge)
                    
                    # Process alternative forms from definitions (new field from parser)
                    # These are simple variant forms extracted from "Alternative form of X" in definitions
                    for alt_from_def in defn.get('alternative_forms_from_definitions', []):
                        variant_form = alt_from_def.get('form')
                        if variant_form:
                            # This lemma is an alternative of variant_form
                            variant_id = self.get_or_create_node_id('cop', variant_form, etymology_index=etym_idx)
                            
                            # Try to find the target variant in existing networks
                            variant_node = None
                            for net in self.networks.values():
                                variant_node = next((n for n in net['nodes'] if n['id'] == variant_id), None)
                                if variant_node:
                                    break
                            
                            # If target not found, create placeholder
                            if not variant_node:
                                variant_node = self.create_node(variant_id, 'cop', variant_form, pos, [])
                            
                            # Add variant node to current network if not already there
                            if not any(n['id'] == variant_id for n in network['nodes']):
                                network['nodes'].append(variant_node)
                            
                            # Create VARIANT edge from variant_form to this lemma
                            edge_exists = any(e.get('from') == variant_id and e.get('to') == cop_id 
                                            for e in network['edges'])
                            if not edge_exists:
                                edge = {
                                    'from': variant_id,
                                    'to': cop_id,
                                    'type': 'VARIANT',
                                    'notes': f'Alternative form of {variant_form} (from definition)'
                                }
                                network['edges'].append(edge)
                    
                    # Add derived terms
                    for derived_term in defn.get('derived_terms', []):
                        if derived_term:
                            derived_id = self.get_or_create_node_id('cop', derived_term)
                            derived_node = self.create_node(
                                derived_id, 'cop', derived_term, pos, []
                            )
                            
                            if not any(n['id'] == derived_id for n in network['nodes']):
                                network['nodes'].append(derived_node)
                                node_count += 1
                            
                            # Create DERIVED edge (base → derived)
                            edge = {
                                'from': cop_id,
                                'to': derived_id,
                                'type': 'DERIVED',
                                'notes': f'Derived from {lemma_form}'
                            }
                            network['edges'].append(edge)
                
                # Add etymology components (compound/affix relationships)
                # ONLY for compounds - prefix/suffix should use DERIVED edges instead
                # Special case: Egyptian components in Coptic etymology should connect to Demotic ancestor
                for component_info in etym.get('etymology_components', []):
                    component_form = component_info.get('form')
                    component_role = component_info.get('role', 'base')  # prefix, suffix, or base
                    template_type = component_info.get('template_type', 'compound')
                    component_lang = component_info.get('language', 'cop')  # Default to Coptic
                    
                    if component_form:
                        # Get the main node for this etymology
                        definitions = etym.get('definitions', [])
                        if not definitions:
                            continue  # Skip if no definitions
                        
                        main_defn = definitions[0]
                        main_pos = main_defn.get('part_of_speech', 'unknown')
                        main_meanings = main_defn.get('definitions', [])
                        main_id = self.get_or_create_node_id('cop', lemma_form, etymology_index=etym_idx)
                        
                        # Special case: Egyptian components with Demotic ancestor
                        # These should connect to the Demotic word, not the Coptic word
                        if component_lang == 'egy' and ancestor_lang_dem == 'egx-dem' and ancestor_form_dem:
                            # Create Egyptian node
                            comp_id = self.get_or_create_node_id('egy', component_form)
                            comp_node = self.create_node(comp_id, 'egy', component_form, 'word', [])
                            
                            if not any(n['id'] == comp_id for n in network['nodes']):
                                network['nodes'].append(comp_node)
                                node_count += 1
                            
                            # Create COMPONENT edge to Demotic ancestor
                            dem_id = self.get_or_create_node_id('dem', ancestor_form_dem)
                            edge = {
                                'from': comp_id,
                                'to': dem_id,
                                'type': 'COMPONENT',
                                'notes': f'Egyptian component of Demotic compound'
                            }
                            # Check if edge already exists
                            if not any(e.get('from') == comp_id and e.get('to') == dem_id for e in network['edges']):
                                network['edges'].append(edge)
                            continue
                        
                        # For prefix/suffix formations: treat as DERIVED (base → derived)
                        if template_type in ['prefix', 'suffix', 'affix', 'confix']:
                            # Only create edge from base word(s), not from affixes
                            if component_role == 'base':
                                # First, check if this base component already exists GLOBALLY
                                # (ignoring etymology_index to avoid duplicates)
                                # Search in ALL networks, not just the current one
                                existing_component = None
                                for other_net in self.networks.values():
                                    existing_component = next((n for n in other_net['nodes'] 
                                                              if n.get('language') == component_lang 
                                                              and n.get('form') == component_form), None)
                                    if existing_component:
                                        break
                                
                                if existing_component:
                                    component_id = existing_component['id']
                                    # Add the existing node to current network if not already there
                                    if not any(n['id'] == component_id for n in network['nodes']):
                                        network['nodes'].append(existing_component)
                                else:
                                    component_id = self.get_or_create_node_id(component_lang, component_form)
                                    component_node = self.create_node(
                                        component_id, component_lang, component_form, 'word', []
                                    )
                                    network['nodes'].append(component_node)
                                    node_count += 1
                                
                                # Create DERIVED edge (base → affixed word)
                                edge = {
                                    'from': component_id,
                                    'to': main_id,
                                    'type': 'DERIVED',
                                    'notes': f'Affixed with {template_type}'
                                }
                                network['edges'].append(edge)
                                
                                # If the main word has a Demotic/Egyptian ancestor, the base word likely does too
                                # Connect base word to same ancestor
                                if ancestor_lang_dem == 'egx-dem' and ancestor_form_dem:
                                    dem_id = self.get_or_create_node_id('dem', ancestor_form_dem)
                                    desc_edge = {
                                        'from': dem_id,
                                        'to': component_id,
                                        'type': 'DESCENDS',
                                        'notes': f'Coptic base word from Demotic'
                                    }
                                    # Check if edge already exists
                                    if not any(e.get('from') == dem_id and e.get('to') == component_id for e in network['edges']):
                                        network['edges'].append(desc_edge)
                                elif ancestor_lang_dem == 'egy' and ancestor_form_dem:
                                    egy_id = self.get_or_create_node_id('egy', ancestor_form_dem)
                                    desc_edge = {
                                        'from': egy_id,
                                        'to': component_id,
                                        'type': 'DESCENDS',
                                        'notes': f'Coptic base word from Egyptian'
                                    }
                                    # Check if edge already exists
                                    if not any(e.get('from') == egy_id and e.get('to') == component_id for e in network['edges']):
                                        network['edges'].append(desc_edge)
                        
                        # For compound formations: use COMPONENT edges for all parts
                        elif template_type == 'compound':
                            component_id = self.get_or_create_node_id('cop', component_form)
                            component_node = self.create_node(
                                component_id, 'cop', component_form, 'word', []
                            )
                            
                            if not any(n['id'] == component_id for n in network['nodes']):
                                network['nodes'].append(component_node)
                                node_count += 1
                            
                            # Create COMPONENT edge (component → compound)
                            edge = {
                                'from': component_id,
                                'to': main_id,
                                'type': 'COMPONENT',
                                'notes': f'Component of compound'
                            }
                            network['edges'].append(edge)
        
        return node_count
    
    def export_networks(self, output_file):
        """Export networks to JSON file"""
        # Convert to list format for easier processing
        networks_list = []
        for network_id, network in self.networks.items():
            network['network_id'] = network_id
            networks_list.append(network)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(networks_list, f, ensure_ascii=False, indent=2)
        
        print(f"\nExported {len(networks_list)} networks to {output_file}")
        
        # Print statistics
        total_nodes = sum(len(n['nodes']) for n in networks_list)
        total_edges = sum(len(n['edges']) for n in networks_list)
        
        print(f"\nStatistics:")
        print(f"  Total networks: {len(networks_list)}")
        print(f"  Total nodes: {total_nodes}")
        print(f"  Total edges: {total_edges}")
        
        # Count by relationship type
        edge_types = defaultdict(int)
        for network in networks_list:
            for edge in network['edges']:
                edge_types[edge['type']] += 1
        
        print(f"\nEdge types:")
        for edge_type, count in sorted(edge_types.items()):
            print(f"  {edge_type}: {count}")
        
        # Count nodes by language
        lang_counts = defaultdict(int)
        for network in networks_list:
            for node in network['nodes']:
                lang_counts[node['language']] += 1
        
        print(f"\nNodes by language:")
        for lang, count in sorted(lang_counts.items()):
            print(f"  {lang}: {count}")
    
    def merge_alternative_form_networks(self):
        """
        Merge networks where one node is an 'alternative form of' another node  
        that ended up in a different network (due to processing order).
        """
        merged_count = 0
        networks_to_remove = set()
        
        # Find all VARIANT edges that point to nodes in other networks
        for source_net_id, source_network in list(self.networks.items()):
            for edge in source_network['edges']:
                if edge['type'] == 'VARIANT' and 'Alternative form of' in edge.get('notes', ''):
                    # This is an alternative form edge
                    target_node_id = edge['from']  # The target of "alternative form of"
                    variant_node_id = edge['to']    # The variant form
                    
                    # Find which network contains the target
                    target_network_id = None
                    for net_id, network in self.networks.items():
                        if net_id != source_net_id and any(n['id'] == target_node_id for n in network['nodes']):
                            target_network_id = net_id
                            break
                    
                    # If target is in a different network, merge them
                    if target_network_id and target_network_id != source_net_id:
                        target_network = self.networks[target_network_id]
                        
                        # Merge source network into target network
                        for node in source_network['nodes']:
                            if not any(n['id'] == node['id'] for n in target_network['nodes']):
                                target_network['nodes'].append(node)
                        
                        for edge_item in source_network['edges']:
                            if not any(e == edge_item for e in target_network['edges']):
                                target_network['edges'].append(edge_item)
                        
                        # Mark source network for removal
                        networks_to_remove.add(source_net_id)
                        merged_count += 1
                        break  # Move to next network
        
        # Remove merged networks
        for net_id in networks_to_remove:
            del self.networks[net_id]
        
        return merged_count
    
    def cleanup_coptic_routing(self):
        """
        Reroute Egyptian→Coptic DESCENDS edges through Demotic when Demotic descendant exists.
        Only reroute if there's an Egyptian→Demotic edge, ensuring the Demotic node is
        actually descended from that Egyptian word.
        """
        rerouted_count = 0
        removed_count = 0
        
        for network_id, network in self.networks.items():
            # Find all Egyptian→Coptic DESCENDS edges that could potentially be rerouted
            for edge in network['edges'][:]:  # Copy list to avoid modification during iteration
                if edge['type'] != 'DESCENDS':
                    continue
                
                # Get source and target nodes
                source_node = next((n for n in network['nodes'] if n['id'] == edge['from']), None)
                target_node = next((n for n in network['nodes'] if n['id'] == edge['to']), None)
                
                if not source_node or not target_node:
                    continue
                
                # Check if it's Egyptian→Coptic (including dialect variants like cop-boh, cop-sah)
                if source_node['language'] == 'egy' and target_node['language'].startswith('cop'):
                    # Find Demotic nodes that are descendants of THIS Egyptian word
                    # Look for Egyptian→Demotic edges from the same Egyptian node
                    egy_to_dem_edges = [
                        e for e in network['edges']
                        if (e['type'] == 'DESCENDS' and 
                            e['from'] == source_node['id'] and
                            next((n for n in network['nodes'] if n['id'] == e['to'] and n['language'] in ['dem', 'egx-dem']), None))
                    ]
                    
                    # If there's a Demotic descendant of this Egyptian word, reroute through it
                    if egy_to_dem_edges:
                        # Use the first Demotic descendant
                        demotic_id = egy_to_dem_edges[0]['to']
                        demotic_node = next((n for n in network['nodes'] if n['id'] == demotic_id), None)
                        
                        # Only reroute if the Demotic node has meanings (not a placeholder)
                        if demotic_node and demotic_node.get('meanings'):
                            # Check if Demotic→Coptic edge already exists
                            edge_exists = any(
                                e['type'] == 'DESCENDS' and 
                                e['from'] == demotic_id and 
                                e['to'] == edge['to']
                                for e in network['edges']
                            )
                            
                            if not edge_exists:
                                # Reroute: change source from Egyptian to Demotic
                                edge['from'] = demotic_id
                                rerouted_count += 1
                            else:
                                # Edge already exists, mark this one for removal
                                edge['_remove'] = True
                                removed_count += 1
            
            # Remove any marked duplicate edges
            network['edges'] = [e for e in network['edges'] if not e.get('_remove', False)]
        
        return rerouted_count + removed_count

    def deduplicate_nodes(self):
        """
        After all networks are built and merged, deduplicate nodes that have the same
        (language, form) but different etymology_index. This happens when a component
        creates a node before the main lemma is processed.
        
        For each duplicate set:
        - Keep the node with an explicit etymology_index (from a lemma page)
        - Redirect all edges from duplicates to the kept node
        - Remove duplicate nodes
        """
        dedup_count = 0
        
        for network_id, network in self.networks.items():
            # Build a map from (language, form, hieroglyphs) to list of nodes
            # For Egyptian, hieroglyphs differentiate true variants
            # For other languages, hieroglyphs will be None so this still works
            form_to_nodes = {}
            for node in network['nodes']:
                # Include hieroglyphs in key for Egyptian to preserve hieroglyphic variants
                if node['language'] == 'egy':
                    key = (node['language'], node['form'], node.get('hieroglyphs'))
                else:
                    key = (node['language'], node['form'], None)
                    
                if key not in form_to_nodes:
                    form_to_nodes[key] = []
                form_to_nodes[key].append(node)
            
            # Find duplicates
            for key, nodes in form_to_nodes.items():
                if len(nodes) <= 1:
                    continue
                
                # Prefer node with etymology_index (from lemma page) over component-created nodes
                nodes_with_etym = [n for n in nodes if n.get('etymology_index') is not None]
                nodes_without_etym = [n for n in nodes if n.get('etymology_index') is None]
                
                # Choose which node to keep
                if nodes_with_etym:
                    keep_node = nodes_with_etym[0]  # Keep the first one with etymology_index
                    remove_nodes = nodes_with_etym[1:] + nodes_without_etym
                else:
                    keep_node = nodes[0]  # Keep the first one
                    remove_nodes = nodes[1:]
                
                if not remove_nodes:
                    continue
                
                keep_id = keep_node['id']
                remove_ids = {n['id'] for n in remove_nodes}
                
                # Redirect all edges from removed nodes to kept node
                for edge in network['edges']:
                    if edge['from'] in remove_ids:
                        edge['from'] = keep_id
                    if edge['to'] in remove_ids:
                        edge['to'] = keep_id
                
                # Remove duplicate nodes
                network['nodes'] = [n for n in network['nodes'] if n['id'] not in remove_ids]
                dedup_count += len(remove_ids)
                
                # Merge meanings and other properties from removed nodes into kept node
                for removed_node in remove_nodes:
                    # Merge meanings
                    if removed_node.get('meanings'):
                        if not keep_node.get('meanings'):
                            keep_node['meanings'] = []
                        for meaning in removed_node['meanings']:
                            if meaning not in keep_node['meanings']:
                                keep_node['meanings'].append(meaning)
                    
                    # Merge variant forms
                    if removed_node.get('variant_forms'):
                        if not keep_node.get('variant_forms'):
                            keep_node['variant_forms'] = []
                        for variant in removed_node['variant_forms']:
                            if variant not in keep_node['variant_forms']:
                                keep_node['variant_forms'].append(variant)
        
        # Remove duplicate edges that might have been created
        for network_id, network in self.networks.items():
            edges_seen = set()
            unique_edges = []
            for edge in network['edges']:
                # Skip self-loops (edges where from == to)
                if edge['from'] == edge['to']:
                    continue
                
                edge_key = (edge['from'], edge['to'], edge['type'])
                if edge_key not in edges_seen:
                    edges_seen.add(edge_key)
                    unique_edges.append(edge)
            network['edges'] = unique_edges
        
        print(f"   Merged {dedup_count} duplicate nodes")
        return dedup_count

    def merge_networks_with_shared_nodes(self):
        """
        Merge networks that share common nodes. Networks sharing any node should be unified
        into a single network, as they represent the same etymological family.
        
        Excludes common grammatical morphemes from triggering merges to prevent
        creating one giant super-network.
        """
        print("\nMerging networks with shared nodes...")
        
        # Define grammatical morphemes that should NOT trigger network merges
        # These are suffixes, particles, and very common grammatical words
        GRAMMATICAL_MORPHEMES = {
            # Egyptian suffixes and particles
            ('egy', '-t'),      # feminine suffix
            ('egy', '-w'),      # plural suffix
            ('egy', '-wj'),     # dual suffix
            ('egy', '-tj'),     # dual feminine suffix
            ('egy', '-wt'),     # feminine plural/abstract suffix
            ('egy', 'm'),       # preposition "in/with"
            ('egy', 'n'),       # preposition "to/for"
            ('egy', 'r'),       # preposition "to/at"
            ('egy', 'ḥr'),      # preposition "on/upon"
            ('egy', 'ḫr'),      # preposition "under"
            ('egy', 'ḥnꜥ'),     # preposition "with"
            ('egy', 'nj'),      # negative/genitive
            ('egy', '.j'),      # suffix pronoun 1sg
            ('egy', '.k'),      # suffix pronoun 2sg masc
            ('egy', '.ṯ'),      # suffix pronoun 2sg fem
            ('egy', '.f'),      # suffix pronoun 3sg masc
            ('egy', '.s'),      # suffix pronoun 3sg fem
            ('egy', '.n'),      # suffix pronoun 1pl
            ('egy', '.ṯn'),     # suffix pronoun 2pl
            ('egy', '.sn'),     # suffix pronoun 3pl
            
            # Very common Egyptian words that appear as components everywhere
            ('egy', 'rꜥ'),      # sun, Ra (appears in many names)
            ('egy', 'pr'),      # house (pr-ꜥꜣ = pharaoh, etc.)
            ('egy', 'nswt'),    # king (in many royal titles)
            ('egy', 'jb'),      # heart (in many compound words)
            ('egy', 'ꜥnḫ'),     # life (in many phrases)
            ('egy', 'nfr'),     # good/beautiful (common component)
            ('egy', 'ḥtp'),     # peace/offering (common in names)
            
            # Coptic prefixes and common particles
            ('cop', 'ⲛ'),       # prefix/article
            ('cop', 'ⲙ'),       # preposition/negative
            ('cop', 'ⲡ'),       # article
            ('cop', 'ⲧ'),       # article feminine
            ('cop', 'ⲛⲉ'),      # plural article
            ('cop', 'ⲛⲓ'),      # plural article
            
            # Common dialectal markers that shouldn't merge everything
            ('cop', 'Old Coptic'),
            ('cop', 'Faiyumic'),
            ('cop', 'OC'),
        }
        
        # Convert dict to list with indices for processing
        network_ids = list(self.networks.keys())
        network_list = [self.networks[nid] for nid in network_ids]
        
        # Build a map from node_id to set of network indices containing that node
        # EXCLUDE grammatical morphemes from this map
        node_to_networks = {}
        for net_idx, network in enumerate(network_list):
            for node in network['nodes']:
                # Skip grammatical morphemes
                if (node['language'], node['form']) in GRAMMATICAL_MORPHEMES:
                    continue
                
                node_id = (
                    node['language'],
                    node['form'],
                    node.get('period'),
                    node.get('dialect'),
                    tuple(node.get('hieroglyphs') or []),
                    node.get('etymology_index', 0)
                )
                if node_id not in node_to_networks:
                    node_to_networks[node_id] = set()
                node_to_networks[node_id].add(net_idx)
        
        # Find groups of networks that should be merged (using union-find)
        parent = list(range(len(network_list)))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        # Union networks that share any node
        # BUT: Don't merge networks with different root etymology_index
        # This prevents different etymologies of the same lemma from being merged
        for node_id, net_indices in node_to_networks.items():
            if len(net_indices) > 1:
                net_list = list(net_indices)
                # Check if all networks have the same root etymology_index
                root_etyms = [network_list[idx]['root_node'].get('etymology_index') for idx in net_list]
                # Only merge if etymology indices match (or are None for old-style nodes)
                if len(set(e for e in root_etyms if e is not None)) <= 1:
                    for i in range(1, len(net_list)):
                        union(net_list[0], net_list[i])
        
        # Group networks by their root parent
        merge_groups = {}
        for net_idx in range(len(network_list)):
            root = find(net_idx)
            if root not in merge_groups:
                merge_groups[root] = []
            merge_groups[root].append(net_idx)
        
        # Merge networks in each group and rebuild dictionary
        merged_networks = {}
        merges_performed = 0
        new_net_id = 0
        
        for root, net_indices in merge_groups.items():
            if len(net_indices) == 1:
                # No merging needed - keep original
                merged_networks[f'N{new_net_id:05d}'] = network_list[net_indices[0]]
                new_net_id += 1
            else:
                # Merge multiple networks
                merges_performed += len(net_indices) - 1
                merged_net = {
                    'nodes': [],
                    'edges': []
                }
                
                # Build ID mapping: old node IDs -> canonical node ID
                # Multiple nodes with different IDs might represent same conceptual node
                id_mapping = {}
                seen_nodes = set()
                
                for net_idx in net_indices:
                    for node in network_list[net_idx]['nodes']:
                        node_id = (
                            node['language'],
                            node['form'],
                            node.get('period'),
                            node.get('dialect'),
                            tuple(node.get('hieroglyphs') or []),
                            node.get('etymology_index', 0)
                        )
                        
                        if node_id not in seen_nodes:
                            # First time seeing this conceptual node - use its ID as canonical
                            seen_nodes.add(node_id)
                            canonical_id = node['id']
                            id_mapping[node['id']] = canonical_id
                            merged_net['nodes'].append(node)
                        else:
                            # Already have this node - map this ID to the canonical one
                            # Find the canonical ID
                            for existing_node in merged_net['nodes']:
                                existing_node_id = (
                                    existing_node['language'],
                                    existing_node['form'],
                                    existing_node.get('period'),
                                    existing_node.get('dialect'),
                                    tuple(existing_node.get('hieroglyphs') or []),
                                    existing_node.get('etymology_index', 0)
                                )
                                if existing_node_id == node_id:
                                    id_mapping[node['id']] = existing_node['id']
                                    break
                
                # Collect all edges, remapping IDs and deduplicating
                seen_edges = set()
                for net_idx in net_indices:
                    for edge in network_list[net_idx]['edges']:
                        # Remap the IDs
                        from_id = id_mapping.get(edge['from'], edge['from'])
                        to_id = id_mapping.get(edge['to'], edge['to'])
                        
                        edge_id = (from_id, to_id, edge['type'])
                        if edge_id not in seen_edges:
                            seen_edges.add(edge_id)
                            # Create new edge with remapped IDs
                            new_edge = edge.copy()
                            new_edge['from'] = from_id
                            new_edge['to'] = to_id
                            merged_net['edges'].append(new_edge)
                
                merged_networks[f'N{new_net_id:05d}'] = merged_net
                new_net_id += 1
        
        original_count = len(self.networks)
        self.networks = merged_networks
        
        print(f"Merged {merges_performed} networks ({original_count} → {len(self.networks)})")
        return merges_performed

def main():
    # Load the three parsed files
    print("Loading parsed Wiktionary data...")
    
    with open('egyptian_lemmas_parsed_mwp.json', 'r', encoding='utf-8') as f:
        egy_data = json.load(f)
    
    with open('demotic_lemmas_parsed_mwp.json', 'r', encoding='utf-8') as f:
        dem_data = json.load(f)
    
    with open('coptic_lemmas_parsed_mwp.json', 'r', encoding='utf-8') as f:
        cop_data = json.load(f)
    
    print(f"Loaded {len(egy_data)} Egyptian, {len(dem_data)} Demotic, {len(cop_data)} Coptic lemmas")
    
    # Build networks
    builder = LemmaNetworkBuilder()
    networks = builder.build_networks_from_parsed_data(egy_data, dem_data, cop_data)
    
    # Merge networks that share common nodes
    builder.merge_networks_with_shared_nodes()
    
    # Export
    builder.export_networks('lemma_networks.json')
    
    print("\n" + "="*80)
    print("Network building complete!")
    print("\nThe output file 'lemma_networks.json' contains:")
    print("- Each network represents a lemma's evolution across time/languages")
    print("- Nodes: word forms in different languages/periods/dialects")
    print("- Edges: EVOLVES (temporal), DESCENDS (cross-language), VARIANT (spelling)")
    print("\nThis can be used to train a model that translates between:")
    print("- Different periods of Egyptian (Old Kingdom → New Kingdom → Late Period)")
    print("- Egyptian → Demotic → Coptic")
    print("- Different Coptic dialects (Sahidic, Bohairic, etc.)")

if __name__ == '__main__':
    main()
