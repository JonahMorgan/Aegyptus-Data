"""
Simple HTTP Server for Egyptian Lemma Network Visualizer

This script starts a local web server to view the network visualization.
The visualization will be available at http://localhost:8000
"""

import http.server
import socketserver
import webbrowser
import os
import shutil
from pathlib import Path

PORT = 8000

# Change to the visualize directory
script_dir = Path(__file__).parent
os.chdir(script_dir)

# Copy JSON file if it doesn't exist in visualize directory
json_source = script_dir.parent / 'archive' / 'lemma_networks.json'
json_dest = script_dir / 'lemma_networks.json'

if json_source.exists() and not json_dest.exists():
    print(f"Copying lemma_networks.json to visualize directory...")
    shutil.copy2(json_source, json_dest)
    print(f"✓ JSON file copied")

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Get default translation
        translated_path = super().translate_path(path)
        
        # If the file is a json file, doesn't exist here, but exists in the parent directory, serve it from parent
        if translated_path.endswith('.json') and not os.path.exists(translated_path):
            parent_path = os.path.join(os.path.dirname(os.getcwd()), os.path.basename(translated_path))
            if os.path.exists(parent_path):
                return parent_path
                
        return translated_path

    def do_GET(self):
        # Redirect root to index.html
        if self.path == '/':
            self.path = '/index.html'
        
        # For JSON files, serve as UTF-8 (transcoding any legacy UTF-16 files)
        if self.path.endswith('.json'):
            file_path = self.translate_path(self.path)
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        raw = f.read()
                    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                        encoded = raw.decode('utf-16').encode('utf-8')
                    else:
                        encoded = raw.decode('utf-8-sig').encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(encoded)))
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                    super(http.server.SimpleHTTPRequestHandler, self).end_headers()
                    self.wfile.write(encoded)
                    return
                except (UnicodeDecodeError, UnicodeError):
                    # Not UTF-16, fall through to default handler
                    pass
        
        return super().do_GET()
    
    def end_headers(self):
        # Add CORS headers to allow loading JSON
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Content-Type', 'application/json' if self.path.endswith('.json') else self.guess_type(self.path))
        super().end_headers()

    def log_message(self, format, *args):
        # Custom log format
        if not self.path.endswith('.ico'):  # Suppress favicon errors
            print(f"[Server] {self.address_string()} - {format % args}")

def main():
    print("="*80)
    print("Egyptian Lemma Network Visualizer - Local Server")
    print("="*80)
    print(f"\nStarting server on port {PORT}...")
    print(f"Server directory: {script_dir}")
    print(f"\nOpen your browser and navigate to:")
    print(f"  → http://localhost:{PORT}")
    print(f"\nPress Ctrl+C to stop the server")
    print("="*80 + "\n")
    
    # Try to open browser automatically
    try:
        webbrowser.open(f'http://localhost:{PORT}')
        print("✓ Browser opened automatically\n")
    except:
        print("⚠ Could not open browser automatically. Please open manually.\n")
    
    # Start server
    with socketserver.TCPServer(("", PORT), MyHTTPRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n" + "="*80)
            print("Server stopped by user")
            print("="*80)

if __name__ == '__main__':
    main()
