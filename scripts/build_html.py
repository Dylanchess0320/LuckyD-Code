"""Build the complete voice-to-voice HTML interface for DeepSeek Code.

This script:
  - Extracts CSS, HTML body, and JS from the monolithic index.html into
    separate source files under templates/src/
  - Reassembles them back into the final index.html
  - Adds cache-busting version string

Usage:
  python build_html.py              # Rebuild index.html from src/ components
  python build_html.py --extract    # Extract components from current index.html
"""

import os
import sys
import re
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE, "luckyd_code", "templates", "src")
INDEX_HTML = os.path.join(BASE, "luckyd_code", "templates", "index.html")

# Ensure src dir exists
os.makedirs(SRC_DIR, exist_ok=True)


def extract_components():
    """Extract CSS, body HTML, and JS from the current index.html into src/ files."""
    print(f"Reading: {INDEX_HTML}")
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract <style>...</style>
    style_match = re.search(r"<style>(.*?)</style>", content, re.DOTALL)
    if style_match:
        css = style_match.group(1).strip()
        css_path = os.path.join(SRC_DIR, "style.css")
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(css)
        print(f"  -> Extracted CSS ({len(css)} chars) -> src/style.css")

    # Extract <body> contents, stripping CDN scripts and the inline JS block
    body_match = re.search(r"<body>(.*?)</body>", content, re.DOTALL)
    if body_match:
        raw_body = body_match.group(1)
        # Remove CDN script tags from body
        clean_body = re.sub(
            r'<script src="https?://[^"]+\.js"[^>]*></script>\s*',
            '', raw_body
        )
        # Remove the Auto-generated inline script block from body
        clean_body = re.sub(
            r'<script>\s*// === Auto-generated.*?</script>\s*',
            '', clean_body, flags=re.DOTALL
        )
        body_html = clean_body.strip()
        body_path = os.path.join(SRC_DIR, "body.html")
        with open(body_path, "w", encoding="utf-8") as f:
            f.write(body_html)
        print(f"  -> Extracted body HTML ({len(body_html)} chars) -> src/body.html")

    # Extract <script src="..."> CDN tags
    cdn_scripts = re.findall(
        r'(<script src="https?://[^"]+\.js"[^>]*></script>)', content
    )
    if cdn_scripts:
        cdn_path = os.path.join(SRC_DIR, "cdn.txt")
        with open(cdn_path, "w", encoding="utf-8") as f:
            f.write("\n".join(cdn_scripts))
        print(f"  -> Extracted {len(cdn_scripts)} CDN scripts -> src/cdn.txt")

    # Extract inline <script>...</script> (the app logic, not CDN ones)
    script_match = re.search(
        r"<script>\s*(// Configure marked.*?)</script>", content, re.DOTALL
    )
    if script_match:
        js = script_match.group(1).strip()
        js_path = os.path.join(SRC_DIR, "app.js")
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(js)
        print(f"  -> Extracted JS ({len(js)} chars) -> src/app.js")

    print("\nDone! Components extracted to templates/src/")
    print("Run 'python build_html.py' to reassemble them.")


def build():
    """Reassemble index.html from src/ components."""
    css_path = os.path.join(SRC_DIR, "style.css")
    body_path = os.path.join(SRC_DIR, "body.html")
    js_path = os.path.join(SRC_DIR, "app.js")
    cdn_path = os.path.join(SRC_DIR, "cdn.txt")

    # If src files don't exist, extract first
    if not all(os.path.exists(p) for p in [css_path, body_path, js_path]):
        print("Source files not found. Running extract first...\n")
        extract_components()

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()
    with open(body_path, "r", encoding="utf-8") as f:
        body_html = f.read()
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # CDN scripts (optional — use defaults if missing)
    if os.path.exists(cdn_path):
        with open(cdn_path, "r", encoding="utf-8") as f:
            cdn_scripts = f.read().strip()
    else:
        cdn_scripts = (
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>\n'
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>'
        )

    version = datetime.now().strftime("%Y%m%d%H%M")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="DeepSeek Code">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-192.png">
<title>DeepSeek Code</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
/* === Auto-generated by build_html.py v{version} === */
{css}
</style>
</head>
<body>
{body_html}
{cdn_scripts}
<script>
// === Auto-generated by build_html.py v{version} ===
{js}
</script>
</body>
</html>"""

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = len(html) / 1024
    print(f"[OK] Built: {INDEX_HTML}")
    print(f"   Size: {size_kb:.1f} KB  |  Version: {version}")
    print(f"   CSS: {len(css)} chars  |  Body: {len(body_html)} chars  |  JS: {len(js)} chars")


if __name__ == "__main__":
    if "--extract" in sys.argv or "-e" in sys.argv:
        extract_components()
    else:
        build()
