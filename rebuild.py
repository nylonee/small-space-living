#!/usr/bin/env python3
"""
Rebuild all site HTML pages from templates with current config.
Patches inline affiliate links in existing article HTML content.
"""
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = SCRIPT_DIR / 'config.json'

with open(CONFIG_PATH) as f:
    config = json.load(f)

tag = config['amazon']['tag']
base_url = config['amazon']['base_url']
public_dir = Path(config['generation']['public_dir'])

# Import the generator for its render methods
sys.path.insert(0, str(SCRIPT_DIR))
from generate import ContentGenerator

gen = ContentGenerator(str(CONFIG_PATH))

# Load article index
with open(gen.index_path) as f:
    articles = json.load(f)

print(f"Rebuilding {len(articles)} article pages...")

# Fix canonical/og:url in article template — the current template
# uses {{ article.slug }}.html but we actually use directory URLs (/slug/)
# We'll fix this when re-rendering

for art in articles:
    slug = art['slug']
    html_path = public_dir / slug / 'index.html'

    if not html_path.exists():
        print(f"  ✗ Missing: {slug}/index.html — skipping")
        continue

    # Read the existing HTML to extract the content div
    existing_html = html_path.read_text()

    # Extract content between <div class="content"> and </div class="content">
    # Use a simple approach: find the content div and its closing tag
    content_match = re.search(
        r'<div class="content">\s*\n(.*?)</div>\s*\n\s*(?=</article>)',
        existing_html, re.DOTALL
    )

    if not content_match:
        # Try looser match
        content_match = re.search(
            r'<div class="content">(.*?)</div>',
            existing_html, re.DOTALL
        )

    if content_match:
        html_content = content_match.group(1)
        # Strip leading/trailing whitespace
        html_content = html_content.strip()
    else:
        print(f"  ⚠ Could not extract content from {slug}/index.html, reading raw file")
        html_content = existing_html

    # ---------------------------------------------------------------
    # Patch old Amazon links in the inline content
    # ---------------------------------------------------------------
    old_domain = r'https://www\.amazon\.com/dp/'
    new_domain = 'https://www.amazon.co.uk/dp/'
    html_content = re.sub(old_domain, new_domain, html_content)

    old_tag = 'tag=smallspaceliv-20'
    new_tag = f'tag={tag}'
    html_content = html_content.replace(old_tag, new_tag)

    # ---------------------------------------------------------------
    # Build the full article dict for the template
    # ---------------------------------------------------------------
    article_for_render = dict(art)  # shallow copy
    article_for_render['html_content'] = html_content

    # ---------------------------------------------------------------
    # Re-render using the template (product grid links auto-update)
    # ---------------------------------------------------------------
    new_html = gen.render_article_html(article_for_render)

    # Fix canonical URL — remove .html from it since we use directory URLs
    new_html = re.sub(
        r'(href|canonical)="https://smallspaceliving\.online/([^"]+)\.html"',
        r'\1="https://smallspaceliving.online/\2/"',
        new_html
    )

    html_path.write_text(new_html)
    print(f"  ✓ {slug}/")

print("\nRebuilding homepage, categories, and sitemap...")
gen._rebuild_static_pages()

print(f"\n✓ Done! All pages rebuilt with:")
print(f"  URL:     {config['amazon']['base_url']}")
print(f"  Tag:     {config['amazon']['tag']}")
print(f"  Locale:  {config['site']['locale']}")
