#!/usr/bin/env python3
import json
import sys

# Check input files
print("Checking input files...")
try:
    with open('egyptian_lemmas_parsed_mwp.json', 'r', encoding='utf-8') as f:
        egy_data = json.load(f)
    print(f"  Egyptian lemmas: {len(egy_data)}")
    if egy_data:
        sample_key = list(egy_data.keys())[0]
        print(f"  Sample: {sample_key}")
except Exception as e:
    print(f"  ERROR loading Egyptian: {e}")
    sys.exit(1)

try:
    with open('demotic_lemmas_parsed_mwp.json', 'r', encoding='utf-8') as f:
        dem_data = json.load(f)
    print(f"  Demotic lemmas: {len(dem_data)}")
except Exception as e:
    print(f"  ERROR loading Demotic: {e}")
    sys.exit(1)

try:
    with open('coptic_lemmas_parsed_mwp.json', 'r', encoding='utf-8') as f:
        cop_data = json.load(f)
    print(f"  Coptic lemmas: {len(cop_data)}")
except Exception as e:
    print(f"  ERROR loading Coptic: {e}")
    sys.exit(1)

# Run builder
print("\nRunning builder...")
try:
    from build_lemma_networks_v2 import EgocentricLemmaNetworkBuilder
    builder = EgocentricLemmaNetworkBuilder()
    builder.build_networks_from_parsed_data(egy_data, dem_data, cop_data)
    print(f"  Networks created: {len(builder.networks)}")
    
    # Check network distribution
    egy_networks = [n for n in builder.networks if any(node['language'] == 'egy' for node in n.get('nodes', []))]
    dem_networks = [n for n in builder.networks if any(node['language'] in ['dem', 'egx-dem'] for node in n.get('nodes', []))]
    cop_networks = [n for n in builder.networks if any(node['language'].startswith('cop') for node in n.get('nodes', []))]
    
    print(f"  - Egyptian-rooted networks: {len(egy_networks)}")
    print(f"  - Demotic-only networks: {len(dem_networks)}")
    print(f"  - Coptic-only networks: {len(cop_networks)}")
    
except Exception as e:
    print(f"  ERROR in builder: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
