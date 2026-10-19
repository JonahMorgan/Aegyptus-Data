"""
Parser for Egyptian, Demotic, and Coptic Wiktionary lemmas using mwparserfromhell.
This is a cleaner, more robust implementation than regex-based parsing.
"""

import json
import mwparserfromhell
from typing import Dict, List, Optional
import sys
from pathlib import Path

def parse_template_params(template) -> Dict[str, str]:
    """Extract all parameters from a template as a dictionary."""
    params = {}
    for param in template.params:
        key = str(param.name).strip()
        value = str(param.value).strip()
        params[key] = value
    return params

def parse_egy_hieroforms(template) -> List[Dict[str, str]]:
    """Parse {{egy-hieroforms}} template into structured alternative forms."""
    params = parse_template_params(template)
    alt_forms = []
    
    # Extract title if present
    title = params.get('title')
    
    # The template format is:
    # {{egy-hieroforms
    # |<hiero>...</hiero>|date1=...|note1=...|read1=...
    # |<hiero>...</hiero>|date2=...|note2=...|read2=...
    # }}
    # Where numbered params (1, 2, 3...) are the hieroglyphs
    # and date1, note1, read1 etc. are metadata for that form
    
    # Collect numbered hieroglyph parameters
    hieroglyphs_by_index = {}
    for i in range(1, 100):  # Reasonable upper limit
        if str(i) in params:
            hieroglyphs_by_index[i] = params[str(i)]
    
    # Build alternative forms from hieroglyphs and their metadata
    for i in sorted(hieroglyphs_by_index.keys()):
        form_entry = {
            'hieroglyphs': hieroglyphs_by_index[i]
        }
        
        # Add metadata if present
        if f'read{i}' in params:
            form_entry['transliteration'] = params[f'read{i}']
        if f'date{i}' in params:
            form_entry['date'] = params[f'date{i}']
        if f'note{i}' in params:
            form_entry['note'] = params[f'note{i}']
        if title:
            form_entry['title'] = title
        
        alt_forms.append(form_entry)
    
    return alt_forms

def extract_definitions(wikicode, level: int = 1):
    """Extract definition lines and quotes."""
    definitions = []
    quotes = []
    text = str(wikicode)
    
    current_block = []
    is_quote = False
    
    def process_block(block, is_qt):
        if not block: return
        raw_text = '\n'.join(block)
        
        if is_qt:
            quotes.append(raw_text.strip())
            return
            
        import mwparserfromhell
        defn_code = mwparserfromhell.parse(raw_text)
        templates = list(defn_code.filter_templates())
        for template in templates:
            name = str(template.name).strip().lower()
            try:
                if name == 'lb':
                    labels = [str(p.value).strip() for p in template.params[1:]]
                    defn_code.replace(template, f"[{', '.join(labels)}]")
                elif name == 'defdate':
                    date_str = list(parse_template_params(template).values())[0] if parse_template_params(template) else ''
                    defn_code.replace(template, f"(dated: {date_str})")
                elif name == 'ng':
                    defn_code.replace(template, list(parse_template_params(template).values())[0] if parse_template_params(template) else '')
                elif name == 'def-uncertain':
                    defn_code.replace(template, '[uncertain]')
                elif name in ['alt form', 'alternative form of', 'altform']:
                    params = list(parse_template_params(template).values())
                    term = params[1] if len(params) > 1 else params[0] if params else ''
                    defn_code.replace(template, f"Alternative form of {term}")
                elif name in ['m', 'l', 'w', 'taxfmt', 'cog', 'inh']:
                    params = list(parse_template_params(template).values())
                    defn_code.replace(template, params[1] if len(params) > 1 else params[0] if params else '')
                elif name == 'q':
                    defn_code.replace(template, ' '.join(parse_template_params(template).values()))
                elif name == 'sup':
                    defn_code.replace(template, '')
                elif name in ['q', 'quote', 'quotation']:
                    quotes.append(str(template))
                    defn_code.replace(template, '')
            except (ValueError, AttributeError):
                pass
                
        clean_text = mwparserfromhell.parse(str(defn_code).strip()).strip_code()
        if clean_text: definitions.append(clean_text)

    for line in text.split('\n'):
        stripped = line.lstrip()
        if stripped.startswith('#*') or stripped.startswith('#:'):
            process_block(current_block, is_quote)
            current_block = [stripped[2:].strip()]
            is_quote = True
        elif stripped.startswith('#'):
            hash_count = len(line) - len(line.lstrip('#'))
            if hash_count == level:
                process_block(current_block, is_quote)
                current_block = [stripped[1:].strip()]
                is_quote = False
        else:
            if current_block:
                current_block.append(line)
                
    process_block(current_block, is_quote)
    return definitions, quotes

def parse_pos_section(section_code, pos_name: str, subsection_level: int) -> Dict:
    """Parse a single part-of-speech section."""
    result = {
        'part_of_speech': pos_name.lower(),
        'parameters': '',
        'definitions': []
    }
    
    # Find the POS template (e.g., {{egy-verb|...}}, {{egy-noun|...}})
    for template in section_code.filter_templates():
        name = str(template.name).strip()
        if name.startswith('egy-') or name.startswith('cop-') or name.startswith('dem-'):
            if any(pos.lower() in name.lower() for pos in ['noun', 'verb', 'adj', 'adv', 'part', 'prep', 'pron', 'num', 'proper']):
                params = parse_template_params(template)
                # Join all parameters into a string
                result['parameters'] = '|'.join(f"{k}={v}" if k else v for k, v in params.items())
                break
    
    # Extract definitions
    defs, quotes = extract_definitions(section_code, level=1)
    result['definitions'] = defs
    result['quotes'] = quotes
    
    # Check definitions for "Alternative form of X" pattern
    variant_forms_from_defs = []
    for defn in result['definitions']:
        # Pattern: "Alternative form of X"  or "Alternative spelling of X"
        import re
        match = re.search(r'(?:Alternative|Alternate)\s+(?:form|spelling|orthography)\s+of\s+(\S+)', defn, re.IGNORECASE)
        if match:
            variant_form = match.group(1).strip()
            # Clean up any remaining wiki markup
            variant_form = mwparserfromhell.parse(variant_form).strip_code()
            if variant_form:
                variant_forms_from_defs.append({'form': variant_form})
    
    if variant_forms_from_defs:
        result['alternative_forms_from_definitions'] = variant_forms_from_defs
    
    # Look for subsections
    sections = section_code.get_sections(levels=[subsection_level])
    
    for subsection in sections:
        heading = subsection.filter_headings()
        if not heading:
            continue
        
        heading_text = str(heading[0].title).strip()
        
        # Inflection
        if heading_text == 'Inflection':
            for template in subsection.filter_templates():
                name = str(template.name).strip()
                if 'decl' in name or 'conj' in name:
                    params = parse_template_params(template)
                    # Extract just the parameters (skip the template name)
                    param_list = []
                    for k, v in params.items():
                        if k:  # Named parameter
                            param_list.append(f"{k}={v}" if k else v)
                        else:  # Positional parameter
                            param_list.append(v)
                    result['inflection'] = '|'.join(param_list)
                    break
        
        # Alternative forms
        elif heading_text == 'Alternative forms':
            alt_forms = []
            for template in subsection.filter_templates():
                name = str(template.name).strip()
                if 'hieroforms' in name:
                    # Egyptian hieroglyphic forms
                    forms = parse_egy_hieroforms(template)
                    alt_forms.extend(forms)
                elif name in ['alter', 'alt']:
                    # Simple alternative forms (used in Coptic/Demotic)
                    # Format: {{alter|lang|form1|form2|...|dialect}}
                    params = [str(p.value).strip() for p in template.params]
                    if len(params) < 2:
                        continue
                    
                    # Skip language code (first param)
                    forms_and_dialect = params[1:]
                    
                    # Last non-empty param might be a dialect
                    dialect = None
                    dialect_names = ['Akhmimic', 'Bohairic', 'Sahidic', 'Fayyumic', 'Lycopolitan']
                    
                    # Find forms and potential dialect
                    forms_in_template = []
                    for val in forms_and_dialect:
                        if val:  # Non-empty
                            if val in dialect_names:
                                dialect = val
                            else:
                                forms_in_template.append(val)
                    
                    # Add each form
                    for form in forms_in_template:
                        form_entry = {'form': form}
                        if dialect:
                            form_entry['dialect'] = dialect
                        alt_forms.append(form_entry)
            
            if alt_forms:
                result['alternative_forms'] = alt_forms
        
        # Usage notes
        elif heading_text == 'Usage notes':
            text = str(subsection).split('\n', 1)[1] if '\n' in str(subsection) else ''
            # Clean up templates
            cleaned = mwparserfromhell.parse(text)
            templates = list(cleaned.filter_templates())
            for template in templates:
                try:
                    name = str(template.name).strip()
                    if name in ['m', 'l', 'w']:
                        params = parse_template_params(template)
                        values = list(params.values())
                        cleaned.replace(template, values[1] if len(values) > 1 else values[0] if values else '')
                except (ValueError, AttributeError):
                    pass
            result['usage_notes'] = cleaned.strip_code().strip()
        
        # Derived terms
        elif heading_text == 'Derived terms':
            derived = []
            for template in subsection.filter_templates():
                name = str(template.name).strip()
                if name == 'l':
                    params = parse_template_params(template)
                    values = list(params.values())
                    if len(values) > 1:
                        derived.append(values[1])
                elif name in ['col', 'col2', 'col3', 'col4', 'col5']:
                    # Column layout with terms (col2 is most common)
                    params = parse_template_params(template)
                    for v in list(params.values())[1:]:  # Skip language code
                        if v and not v.startswith('col'):
                            # Remove template annotations like <t:...>
                            clean_v = v.split('<')[0].strip()
                            if clean_v:
                                derived.append(clean_v)
            if derived:
                result['derived_terms'] = list(set(derived))
        
        # Synonyms
        elif heading_text == 'Synonyms':
            synonyms = []
            for template in subsection.filter_templates():
                name = str(template.name).strip()
                if name == 'l':
                    params = parse_template_params(template)
                    values = list(params.values())
                    if len(values) > 1:
                        synonyms.append(values[1])
                elif name in ['col', 'col2', 'col3', 'col4', 'col5']:
                    # Column layout with terms
                    params = parse_template_params(template)
                    for v in list(params.values())[1:]:  # Skip language code
                        if v and not v.startswith('col'):
                            # Remove template annotations
                            clean_v = v.split('<')[0].strip()
                            if clean_v:
                                synonyms.append(clean_v)
            if synonyms:
                result['synonyms'] = list(set(synonyms))
        
        # Descendants
        elif heading_text == 'Descendants':
            descendants = []
            subsection_text = str(subsection)
            text_lines = []
            parsing_lines = False
            for line in subsection_text.split('\n'):
                if '====' in line or '===' in line:
                    if parsing_lines: break
                    parsing_lines = True
                    continue
                if parsing_lines:
                    text_lines.append(line)
                    
            if not text_lines:
                text_lines = subsection_text.split('\n')
                
            parent_stack = []
            for line in text_lines:
                stripped = line.lstrip()
                if stripped.startswith('*'):
                    level = 0; i = 0
                    while i < len(stripped):
                        if stripped[i] == '*': level += 1; i += 1
                        elif stripped[i] == ':': level += 1; i += 1
                        elif stripped[i] == ' ': i += 1
                        else: break
                    level -= 1
                    
                    line_code = mwparserfromhell.parse(line)
                    templates = list(line_code.filter_templates())
                    
                    # Track which languages we've already processed on THIS line
                    # to avoid duplicates when desc + l/m templates appear together
                    seen_langs_this_line = set()
                    
                    for t_idx, template in enumerate(templates):
                        name = str(template.name).strip().lower()
                        if name in ['desc', 'desctree', 'l', 'link', 'm', 'mention', 'cog', 'inh', 'der']:
                            params = parse_template_params(template)
                            positionals = [v for k, v in params.items() if k.isdigit() or not k]
                            named_params = {k: v for k, v in params.items() if not k.isdigit() and k}
                            
                            if not positionals: continue
                            lang = positionals[0]
                            
                            # If desc/desctree already handled this language on this line,
                            # skip secondary l/m/mention templates for the same language
                            if name in ['l', 'link', 'm', 'mention', 'cog'] and lang in seen_langs_this_line:
                                continue
                            
                            words = positionals[1:]
                            
                            clean_words = []
                            for w in words:
                                # Resolve nested templates like {{l|egx-dem|pr-ꜥꜣ}}
                                if w and '{{' in w:
                                    import re
                                    nested_match = re.search(r'\{\{(?:l|m|link|mention)\|[^|]+\|([^|}]+)', w)
                                    if nested_match:
                                        w = nested_match.group(1).strip()
                                    else:
                                        continue  # Skip unresolvable template text
                                # Skip empty/dash placeholders
                                if w and w != '-':
                                    clean_w = w.split('<')[0].strip()
                                    if clean_w: clean_words.append(clean_w)
                                    
                            if not clean_words:
                                for j in range(1, 10):
                                    if f'alt{j}' in named_params:
                                        w = named_params[f'alt{j}'].lstrip('-').strip()
                                        if w and w not in clean_words: clean_words.append(w)
                                        
                            if not clean_words and 'tr' in named_params:
                                clean_words.append(named_params['tr'].strip())
                            
                            if not clean_words:
                                edge_type = 'inherited'
                                if 'bor' in named_params: edge_type = 'borrowed'
                                elif 'calque' in named_params: edge_type = 'calque'
                                elif 'der' in named_params: edge_type = 'derived'
                                desc_entry = {'language': lang, 'word': None, 'level': level, 'template_type': name, 'edge_type': edge_type, 'params': named_params or None, 'children': [], 'is_language_marker': True, 'dialect': None}
                            else:
                                # Mark this language as seen on this line
                                seen_langs_this_line.add(lang)
                                
                                dialect = None
                                if t_idx + 1 < len(templates):
                                    next_t = templates[t_idx + 1]
                                    if str(next_t.name).strip().lower() in ['q', 'qualifier', 'i']:
                                        q_params = list(parse_template_params(next_t).values())
                                        if q_params: dialect = q_params[0]
                                
                                for w in clean_words:
                                    edge_type = 'inherited'
                                    if 'bor' in named_params: edge_type = 'borrowed'
                                    elif 'calque' in named_params: edge_type = 'calque'
                                    elif 'der' in named_params: edge_type = 'derived'
                                    desc_entry = {'language': lang, 'word': w, 'level': level, 'template_type': name, 'edge_type': edge_type, 'params': named_params or None, 'children': [], 'dialect': dialect}
                            
                                    while parent_stack and parent_stack[-1][0] >= level:
                                        parent_stack.pop()
                                    if parent_stack:
                                        parent_stack[-1][1]['children'].append(desc_entry)
                                    else:
                                        descendants.append(desc_entry)
                                    parent_stack.append((level, desc_entry))
            if descendants: result['descendants'] = descendants

    
    return result

def parse_etymology_section(wikicode, etym_num: Optional[int] = None, pos_level: int = 4) -> Dict:
    """Parse a single etymology section."""
    result = {
        'etymology_text': '',
        'definitions': [],
        'etymology_number': etym_num
    }
    
    # Extract alternative forms from etymology-level sections (common in Coptic)
    etym_alt_forms = []
    alt_forms_sections = wikicode.get_sections(matches='Alternative forms')
    for alt_section in alt_forms_sections:
        for template in alt_section.filter_templates():
            name = str(template.name).strip()
            if name in ['alter', 'alt']:
                # Format: {{alter|lang|form1|form2|...|dialect_code}}
                params = [str(p.value).strip() for p in template.params]
                if len(params) < 2:
                    continue
                
                # Skip language code (first param)
                forms_and_info = params[1:]
                
                # Dialect codes and full names
                dialect_codes = {'L': 'Lycopolitan', 'A': 'Akhmimic', 'B': 'Bohairic', 
                                'S': 'Sahidic', 'F': 'Fayyumic', 'P': 'Proto-Coptic',
                                'V': 'Sub-Akhmimic'}
                dialect_names = set(dialect_codes.values()) | {'Sahidic', 'Bohairic', 'Lycopolitan', 
                                                                'Akhmimic', 'Fayyumic', 'Proto-Coptic',
                                                                'Sub-Akhmimic'}
                
                # Parse parameters: form, optional gloss (empty), dialect codes/names
                i = 0
                while i < len(forms_and_info):
                    form = forms_and_info[i].strip()
                    if not form:
                        i += 1
                        continue
                    
                    # Check if this is a dialect code or name
                    if form in dialect_codes:
                        # Single-letter code
                        if etym_alt_forms:
                            dialect = dialect_codes[form]
                            if 'dialect' not in etym_alt_forms[-1]:
                                etym_alt_forms[-1]['dialect'] = dialect
                    elif form in dialect_names:
                        # Full dialect name
                        if etym_alt_forms:
                            if 'dialect' not in etym_alt_forms[-1]:
                                etym_alt_forms[-1]['dialect'] = form
                    else:
                        # It's a form (not a dialect indicator)
                        form_entry = {'form': form}
                        
                        # Check next param for gloss (usually empty) or dialect
                        if i + 1 < len(forms_and_info):
                            next_param = forms_and_info[i + 1].strip()
                            if next_param in dialect_codes or next_param in dialect_names:
                                # Next param is dialect, will be handled in next iteration
                                pass
                            elif next_param:
                                # Next param might be a gloss (usually empty though)
                                pass
                        
                        etym_alt_forms.append(form_entry)
                    i += 1
    
    # Extract derived terms from etymology-level sections
    etym_derived = []
    derived_sections = wikicode.get_sections(matches='Derived terms')
    for derived_section in derived_sections:
        for template in derived_section.filter_templates():
            name = str(template.name).strip()
            if name in ['l', 'link', 'm', 'mention']:
                params = [str(p.value).strip() for p in template.params]
                if len(params) >= 2:
                    etym_derived.append(params[1])
            elif name in ['col3', 'col4', 'col5']:
                params = [str(p.value).strip() for p in template.params]
                for v in params[1:]:
                    if v and not v.startswith('title='):
                        etym_derived.append(v)
    
    # Extract etymology components (prefix, suffix, compound, etc.)
    etym_components = []
    etym_ancestors = []  # Track {{der}} templates for ancestry
    etym_sections = wikicode.get_sections(matches='Etymology')
    for etym_section in etym_sections:
        for template in etym_section.filter_templates():
            name = str(template.name).strip()
            
            # Parse derived/inherited/borrowed ancestry templates
            if name in ['der', 'derived', 'inh', 'inherited', 'bor', 'borrowed']:
                params = [str(p.value).strip() for p in template.params]
                # Format: {{der|target_lang|source_lang|form|gloss}}
                if len(params) >= 3:
                    source_lang = params[1]
                    source_form = params[2]
                    if source_form:
                        etym_ancestors.append({
                            'language': source_lang,
                            'form': source_form,
                            'type': name
                        })
            
            # Parse mention templates (often show components within der templates)
            elif name in ['m', 'mention', 'l', 'link']:
                params = [str(p.value).strip() for p in template.params]
                # Format: {{m|lang|form|gloss}}
                if len(params) >= 2:
                    lang = params[0]
                    form = params[1]
                    # Only track if it's Egyptian/Demotic (components of compound)
                    if lang in ['egy', 'egx-dem', 'dem'] and form:
                        # Check if this is nested in a der template context
                        # by looking at the parent text
                        parent_text = str(etym_section)
                        if '{{der' in parent_text or '{{compound' in parent_text:
                            etym_components.append({
                                'form': form,
                                'role': 'base',
                                'template_type': 'compound',
                                'language': lang
                            })
            
            # Parse prefix/suffix/compound templates
            if name in ['prefix', 'suffix', 'compound', 'affix', 'af', 'confix', 'pre', 'suf', 'com']:
                # Format: {{prefix|lang|affix|base|gloss1=...|gloss2=...}}
                # For prefix: first component is prefix, rest are base words
                # For suffix: last component is suffix, rest are base words
                # For compound: all are base words
                
                # Get language code from first parameter (should be positional)
                lang_code = ''
                if template.params:
                    first_param_name = str(template.params[0].name).strip()
                    # Positional params have numeric names like '1', '2'
                    if first_param_name.isdigit() or first_param_name == '':
                        lang_code = str(template.params[0].value).strip()
                
                components = []
                component_lang = lang_code  # Default to template language
                
                # Skip language code (first param) and collect non-named params
                for i, param in enumerate(template.params):
                    if i == 0:  # Skip language code
                        continue
                    
                    # Check if this is a named parameter (has a name like t1, gloss1, etc.)
                    param_name = str(param.name).strip()
                    param_value = str(param.value).strip()
                    
                    # Skip named parameters (they have explicit names like t1=, gloss2=, pos1=, etc.)
                    # Positional parameters have numeric names like '1', '2', '3'
                    if param_name and not param_name.isdigit():
                        continue
                    
                    # Skip empty values
                    if not param_value:
                        continue
                    
                    # For Egyptian/Demotic/Coptic, the transliteration uses Latin alphabet
                    # So we should NOT filter out Latin characters for these languages
                    if lang_code in ['egy', 'egx-dem', 'dem', 'cop']:
                        # Accept all non-named positional parameters for Egyptian languages
                        components.append(param_value)
                    else:
                        # For other languages, skip if it's in Latin alphabet (likely English gloss)
                        # BUT keep it if it ends with - (affix marker) or has Egyptian characters
                        if param_value and all(ord(c) < 0x370 for c in param_value if c.isalpha()):
                            # Keep if it ends with - (affix marker) or starts with - (suffix)
                            if not (param_value.endswith('-') or param_value.startswith('-')):
                                continue
                        components.append(param_value)
                
                # Determine role of each component based on template type and affix markers
                for idx, comp in enumerate(components):
                    role = 'base'  # default
                    
                    # Check if component has affix markers (- at start/end)
                    is_prefix_marker = comp.startswith('-') or (comp.endswith('-') and not comp.startswith('-'))
                    is_suffix_marker = comp.endswith('-') and not is_prefix_marker
                    
                    if name in ['prefix', 'pre'] and idx == 0:
                        role = 'prefix'
                    elif name in ['suffix', 'suf'] and idx == len(components) - 1:
                        role = 'suffix'
                    elif name in ['affix', 'af', 'confix']:
                        # For affix/af/confix, check affix markers to determine role
                        # A component ending with '-' (like 's-') is a prefix
                        # A component starting with '-' (like '-t') is a suffix
                        # Otherwise it's a base word
                        if is_prefix_marker:
                            role = 'prefix'
                        elif is_suffix_marker:
                            role = 'suffix'
                        # else: remains 'base'
                    # For compound/com, all remain 'base'
                    
                    etym_components.append({
                        'form': comp,
                        'role': role,
                        'template_type': name,
                        'language': component_lang
                    })
    
    # Extract etymology text (before any POS sections)
    text_before_pos = []
    for node in wikicode.nodes:
        if hasattr(node, 'title') and str(node.title).strip() in [
            'Noun', 'Verb', 'Adjective', 'Adverb', 'Particle', 'Proper noun', 
            'Preposition', 'Pronoun', 'Numeral', 'Letter'
        ]:
            break
        text_before_pos.append(str(node))
    
    if text_before_pos:
        etym_text = ''.join(text_before_pos).strip()
        result['etymology_text'] = etym_text
    
    # Store etymology components
    if etym_components:
        result['etymology_components'] = etym_components
    
    # Store etymology ancestors
    if etym_ancestors:
        result['etymology_ancestors'] = etym_ancestors
    
    # Get POS sections
    pos_sections = wikicode.get_sections(levels=[pos_level])
    
    for section in pos_sections:
        headings = section.filter_headings()
        if not headings:
            continue
        
        pos_name = str(headings[0].title).strip()
        if pos_name in ['Noun', 'Verb', 'Adjective', 'Adverb', 'Particle', 'Proper noun', 
                        'Preposition', 'Pronoun', 'Numeral', 'Letter', 'Determiner']:
            pos_data = parse_pos_section(section, pos_name, pos_level + 1)
            
            # Add etymology-level alternative forms to this POS definition
            if etym_alt_forms and 'alternative_forms' not in pos_data:
                pos_data['alternative_forms'] = etym_alt_forms.copy()
            elif etym_alt_forms and 'alternative_forms' in pos_data:
                # Merge, avoiding duplicates
                existing_forms = {f['form'] for f in pos_data['alternative_forms']}
                for form in etym_alt_forms:
                    if form['form'] not in existing_forms:
                        pos_data['alternative_forms'].append(form)
            
            # Add etymology-level derived terms to this POS definition
            if etym_derived and 'derived_terms' not in pos_data:
                pos_data['derived_terms'] = etym_derived.copy()
            elif etym_derived and 'derived_terms' in pos_data:
                # Merge, avoiding duplicates
                existing_derived = set(pos_data['derived_terms'])
                for term in etym_derived:
                    if term not in existing_derived:
                        pos_data['derived_terms'].append(term)
            
            # Add etymology-level components to this POS definition
            if etym_components and 'etymology_components' not in pos_data:
                pos_data['etymology_components'] = etym_components.copy()
            
            result['definitions'].append(pos_data)
    
    return result

def parse_wikitext(wikitext: str, language: str = 'Egyptian') -> Dict:
    """Parse complete wikitext for a lemma entry."""
    wikicode = mwparserfromhell.parse(wikitext)
    
    result = {
        'pronunciations': [],
        'etymologies': [],
        'related_terms': [],
        'see_also': [],
        'references': ''
    }
    
    # Find the language section
    sections = wikicode.get_sections(levels=[2])
    lang_section = None
    
    for section in sections:
        headings = section.filter_headings()
        if headings and str(headings[0].title).strip() == language:
            lang_section = section
            break
    
    if not lang_section:
        return result
    
    # Extract pronunciation
    pronunciation_sections = lang_section.get_sections(matches='Pronunciation')
    for pron_section in pronunciation_sections:
        for template in pron_section.filter_templates():
            name = str(template.name).strip()
            if 'IPA' in name or 'pron' in name.lower():
                params = parse_template_params(template)
                result['pronunciations'].append('|'.join(f"{k}={v}" for k, v in params.items()))
    
    # Check if there are etymology sections
    etym_sections = lang_section.get_sections(matches=lambda x: 'Etymology' in str(x))
    
    if etym_sections and any('Etymology 1' in str(s) or 'Etymology 2' in str(s) for s in etym_sections):
        # Multiple etymologies - use level 4 (====) for POS
        for i in range(1, 20):  # Reasonable limit
            etym_title = f'Etymology {i}'
            etym_section = lang_section.get_sections(matches=etym_title)
            if etym_section:
                parsed = parse_etymology_section(etym_section[0], etym_num=i, pos_level=4)
                result['etymologies'].append(parsed)
            else:
                break
    else:
        # Single etymology or no explicit etymology section - use level 3 (===) for POS
        parsed = parse_etymology_section(lang_section, pos_level=3)
        result['etymologies'].append(parsed)
    
    # Extract references
    ref_sections = lang_section.get_sections(matches='References')
    if ref_sections:
        result['references'] = str(ref_sections[0]).split('\n', 1)[1].strip() if '\n' in str(ref_sections[0]) else ''
    
    return result

def main():
    """Parse all Egyptian, Demotic, and Coptic lemma files."""
    
    base_dir = Path(__file__).parent
    
    # Define files to process
    files_to_process = [
        ('egyptian_lemmas.json', 'egyptian_lemmas_parsed_mwp.json', 'Egyptian'),
        ('demotic_lemmas.json', 'demotic_lemmas_parsed_mwp.json', 'Demotic'),
        ('coptic_lemmas.json', 'coptic_lemmas_parsed_mwp.json', 'Coptic')
    ]
    
    for input_file, output_file, language in files_to_process:
        input_path = base_dir / input_file
        output_path = base_dir / output_file
        
        if not input_path.exists():
            print(f"Skipping {input_file} - file not found")
            continue
        
        print(f"\nProcessing {input_file}...")
        print(f"Loading data...")
        
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"Found {len(data)} lemmas to parse...")
        
        parsed_data = {}
        
        for idx, (lemma, content) in enumerate(data.items()):
            if (idx + 1) % 100 == 0:
                try:
                    print(f"Processing lemma {idx + 1}/{len(data)}: {lemma}")
                except:
                    print(f"Processing lemma {idx + 1}/{len(data)}")
            
            # Get the appropriate section
            section_key = f'{language.lower()}_section'
            wikitext = content.get(section_key, content.get('full_wikitext', ''))
            
            # Parse the wikitext
            parsed = parse_wikitext(wikitext, language)
            
            # Add metadata
            parsed['lemma'] = lemma
            parsed['full_wikitext'] = content.get('full_wikitext', '')
            parsed[section_key] = wikitext
            
            parsed_data[lemma] = parsed
        
        # Save parsed data
        print(f"Saving parsed data to {output_file}...")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(parsed_data, f, ensure_ascii=False, indent=2)
        
        print(f"Done! Parsed {len(parsed_data)} lemmas.")
        
        # Show sample (skip due to encoding issues on Windows)
        # if parsed_data:
        #     first_lemma = next(iter(parsed_data.keys()))
        #     print(f"\nSample parsed entry for '{first_lemma}':")
        #     print(json.dumps(parsed_data[first_lemma], indent=2, ensure_ascii=False)[:500])
        #     print("...\n")

if __name__ == '__main__':
    main()
