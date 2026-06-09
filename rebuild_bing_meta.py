#!/usr/bin/env python3
"""Re-render all existing articles + static pages with updated templates, then deploy."""
import sys, json, os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, BaseLoader
import re

base_dir = Path('/home/nihal/content-site')
with open(base_dir / 'config.json') as f:
    config = json.load(f)

jinja = Environment(loader=FileSystemLoader(str(base_dir / 'templates')))
def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')
jinja.filters['slugify'] = slugify
def remove_first_h1(html):
    return re.sub(r'<h1>.*?</h1>', '', html, count=1, flags=re.DOTALL)
jinja.filters['remove_first_h1'] = remove_first_h1

articles_dir = Path(config['generation']['output_dir'])
public_dir = Path(config['generation']['public_dir'])

# Load articles
with open(articles_dir / 'index.json') as f:
    articles = json.load(f)

print(f"Re-rendering {len(articles)} articles with updated templates...")

# Re-render each article
for a in articles:
    article_dir = public_dir / a['slug']
    article_dir.mkdir(parents=True, exist_ok=True)
    
    # Load article HTML (it's in index.json as html_content? No, stripped. Need to regenerate.)
    # Actually we need the full article for html_content. Let me check if it's stored separately.
    # The html_content was stripped to keep index small. But the generate.py stores it in
    # public_dir/<slug>/index.html already. We need to re-render from template.
    # The template uses {{ article.html_content }} which needs to be loaded from the existing file.
    
# Actually, re-rendering needs html_content. Let me read the existing files.
    
for a in articles:
    existing_file = public_dir / a['slug'] / 'index.html'
    if existing_file.exists():
        # Read existing content to extract the <div class="content"> section
        with open(existing_file) as f:
            existing_html = f.read()
        
        # Extract the content between <div class="content"> and </div> after it
        content_match = re.search(r'<div class="content">(.*?)</div>\s*(?:\n\s*<div class="affiliate-products)', existing_html, re.DOTALL)
        if content_match:
            a['html_content'] = content_match.group(1)
        else:
            # fallback: just put the whole body content
            body_match = re.search(r'<main>(.*?)</main>', existing_html, re.DOTALL)
            a['html_content'] = body_match.group(1) if body_match else "<p>Content unavailable</p>"
    else:
        a['html_content'] = "<p>Content not found</p>"

# Re-render and write each article
for a in articles:
    template = jinja.get_template('article.html')
    rendered = template.render(site=config['site'], amazon=config['amazon'], article=a)
    article_dir = public_dir / a['slug']
    article_dir.mkdir(parents=True, exist_ok=True)
    with open(article_dir / 'index.html', 'w') as f:
        f.write(rendered)
    print(f"  ✓ /{a['slug']}/")

# Rebuild static pages
print("\nRebuilding static pages...")

# Sort articles
sorted_articles = sorted(articles, key=lambda a: a['date'], reverse=True)

# Build categories
niche_slugs = {nk: slugify(nk) for nk in config['niches']}
categories = {}
for nk, ns in niche_slugs.items():
    count = sum(1 for a in articles if a.get('niche_key') == nk)
    categories[ns] = {
        'display_name': config['niches'][nk]['display_name'],
        'description': config['niches'][nk]['description'],
        'count': count
    }

# Homepage
home_tpl = jinja.get_template('index.html')
with open(public_dir / 'index.html', 'w') as f:
    f.write(home_tpl.render(site=config['site'], articles=sorted_articles[:24], categories=categories))
print("  → Homepage")

# Category pages
for niche_key in config['niches']:
    ns = niche_slugs[niche_key]
    niche = config['niches'][niche_key]
    cat_articles = sorted([a for a in articles if a.get('niche_key') == niche_key], key=lambda a: a['date'], reverse=True)
    cat_dir = public_dir / 'categories' / ns
    cat_dir.mkdir(parents=True, exist_ok=True)
    cat_tpl = jinja.get_template('category.html')
    with open(cat_dir / 'index.html', 'w') as f:
        f.write(cat_tpl.render(site=config['site'], category_name=niche['display_name'],
                                category_description=niche['description'], articles=cat_articles))
print(f"  → {len(config['niches'])} category pages")

# Privacy page
priv_tpl = jinja.get_template('privacy.html')
priv_dir = public_dir / 'privacy'
priv_dir.mkdir(parents=True, exist_ok=True)
with open(priv_dir / 'index.html', 'w') as f:
    f.write(priv_tpl.render(site=config['site']))
print("  → Privacy page")

# Sitemap
site_url = config['site']['url'].rstrip('/')
base_path = config['site'].get('base_path', '')
lines = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
         f'  <url><loc>{site_url}{base_path}/</loc><priority>1.0</priority></url>']
for ns in niche_slugs.values():
    lines.append(f'  <url><loc>{site_url}{base_path}/categories/{ns}/</loc><priority>0.8</priority></url>')
lines.append(f'  <url><loc>{site_url}{base_path}/privacy/</loc><priority>0.3</priority></url>')
for a in articles:
    lines.append(f'  <url><loc>{site_url}{base_path}/{a["slug"]}/</loc><lastmod>{a["date"]}</lastmod><priority>0.6</priority></url>')
lines.append('</urlset>')
with open(public_dir / 'sitemap.xml', 'w') as f:
    f.write('\n'.join(lines))
print("  → Sitemap")

print(f"\n✓ Done! {len(articles)} articles rebuilt and deployed.")
