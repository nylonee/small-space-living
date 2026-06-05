#!/usr/bin/env python3
"""Regenerate body content for all archived articles and re-render HTML files."""

import json
import sys
import os
import re
import datetime
import requests
import markdown as md_lib
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from slugify import slugify

BASE_DIR = Path(__file__).parent

with open(BASE_DIR / 'config.json') as f:
    config = json.load(f)

cfg = config

# Setup Jinja2
jinja = Environment(loader=FileSystemLoader(str(BASE_DIR / 'templates')))

# Load article index
articles_dir = Path(cfg['generation']['output_dir'])
public_dir = Path(cfg['generation']['public_dir'])
with open(articles_dir / 'index.json') as f:
    all_articles = json.load(f)

# Build format lookup by type
formats_by_type = {f['type']: f for f in cfg['article_formats']}

def call_ollama(prompt):
    payload = {
        'model': config['ollama']['model'],
        'prompt': prompt,
        'stream': False,
        'temperature': config['ollama'].get('temperature', 0.7),
        'options': {
            'num_predict': config['ollama'].get('max_tokens', 2048),
            'num_ctx': config['ollama'].get('num_ctx', 4096)
        }
    }
    response = requests.post(
        config['ollama']['url'],
        json=payload,
        timeout=300
    )
    response.raise_for_status()
    return response.json()['response']

def markdown_to_html(md_text):
    return md_lib.markdown(md_text, extensions=['extra', 'nl2br', 'sane_lists'])

def inject_affiliate_links(html_content, category, niche_key, products_to_add):
    """Same logic as generate.py's _inject_affiliate_products but takes products directly."""
    tag = config['amazon']['tag']
    base_url = config['amazon']['base_url']
    
    html = html_content
    linked_asins = set()
    
    # Collect candidates from product brand/name matches
    candidates = []
    for p in products_to_add:
        names_to_match = list(set([p['brand'], p['name']]))
        for keyword in names_to_match:
            if len(keyword) < 3:
                continue
            for m in re.finditer(re.escape(keyword), html, re.IGNORECASE):
                candidates.append((m.start(), m.end(), keyword, p['asin']))
    
    candidates.sort(key=lambda x: x[0], reverse=True)
    
    link_ranges = set()
    for m in re.finditer(r'<a\s[^>]*>.*?</a>', html, re.DOTALL):
        link_ranges.add((m.start(), m.end()))
    
    def overlaps_link(start, end):
        for ls, le in link_ranges:
            if start < le and end > ls:
                return True
        return False
    
    for orig_start, orig_end, keyword, asin in candidates:
        if overlaps_link(orig_start, orig_end):
            continue
        if html[orig_start:orig_end].lower() != keyword.lower():
            continue
        affiliate_url = f"{base_url}/{asin}?tag={tag}"
        link_html = f'<a href="{affiliate_url}" rel="nofollow sponsored" target="_blank">{html[orig_start:orig_end]}</a>'
        html = html[:orig_start] + link_html + html[orig_end:]
        linked_asins.add(asin)
        link_ranges.add((orig_start, orig_start + len(link_html)))
    
    return {'html': html, 'products': products_to_add[:4]}

def build_prompt_for_article(article):
    """Build a regeneration prompt based on the archived article data."""
    title = article['title']
    category = article['category']
    fmt = formats_by_type.get(article['format_type'])
    
    if not fmt:
        print(f"  WARNING: Unknown format type '{article['format_type']}', using topic_overview")
        fmt = {'type': 'topic_overview', 'prompt_template': 'Write a detailed guide about {category} for small spaces in {year}. Provide practical advice and product recommendations.'}
    
    year = datetime.datetime.now().year
    
    # Get products for hints
    products = article.get('products', [])
    product_hints = "\n".join(
        f"- {p['name']} ({p['brand']}) — {p['description']}, around {p['price']}"
        for p in products
    ) if products else ""
    
    product_section = f"\nReal products to feature prominently in this article:\n{product_hints}\n" if product_hints else ""
    
    prompt = f"""<|im_start|>system
You are an expert product reviewer for a website called "Small Space Living". You write detailed, helpful, SEO-optimized product review articles.

CRITICAL: Write a COMPLETE, SUBSTANTIAL article of 800-1500 words. Do NOT just list products. Start with a strong introduction explaining the problem, then provide detailed buying advice, comparison points, and practical tips WITHIN the article body. Include specific product mentions naturally within the text.

Guidelines:
- Write in natural, conversational English
- Use markdown formatting (## for headers, **bold** for emphasis)
- Mention the exact product names listed below naturally within your content
- Every product mention must include: what it is, why it works for small spaces, approximate price
- Target length: 800-1500 words
{product_section}
START YOUR RESPONSE with the article title as a single H1 markdown heading:
# {title}
Then immediately follow with the article content. Do not include any preamble before the title.
<|im_end|>
<|im_start|>user
Write a detailed {fmt['type']} article about: {category}
Title: {title}
<|im_end|>
<|im_start|>assistant
"""
    return prompt

def render_article_html(article, site_config):
    template = jinja.get_template('article.html')
    amazon = {
        'base_url': site_config['amazon']['base_url'],
        'tag': site_config['amazon']['tag']
    }
    site = {
        'title': site_config['site']['title'],
        'url': site_config['site']['url'],
        'base_path': site_config['site'].get('base_path', '')
    }
    return template.render(article=article, site=site, amazon=amazon)

# Process each article
print(f"Regenerating content for {len(all_articles)} articles...")
updated = 0
for i, article in enumerate(all_articles):
    slug = article['slug']
    print(f"\n[{i+1}/{len(all_articles)}] {article['title']}...", flush=True)
    
    # Build prompt and call Ollama
    prompt = build_prompt_for_article(article)
    raw_text = call_ollama(prompt)
    
    if not raw_text or len(raw_text) < 100:
        print(f"  SKIP: Short response ({len(raw_text) if raw_text else 0} chars)")
        continue
    
    # If the model repeated the title, strip it
    cleaned_text = raw_text
    lines = raw_text.split('\n')
    if lines and lines[0].strip().startswith(f'# {article["title"]}'):
        cleaned_text = '\n'.join(lines[1:]).strip() or raw_text
        if not cleaned_text.strip():
            cleaned_text = raw_text
    
    # Convert to HTML and inject affiliate links
    html_content = markdown_to_html(cleaned_text)
    
    products = article.get('products', [])
    
    # Inject affiliate links into body content
    result = inject_affiliate_links(html_content, article['category'], article['niche_key'], products)
    html_content = result['html']
    grid_products = result['products']
    
    # Update article dict for template rendering
    article['html_content'] = html_content
    article['products'] = grid_products
    
    # Render through template
    article_html = render_article_html(article, config)
    
    # Write to correct path
    article_dir = public_dir / slug
    article_dir.mkdir(parents=True, exist_ok=True)
    output_path = article_dir / 'index.html'
    with open(output_path, 'w') as f:
        f.write(article_html)
    
    # Verify content was written
    with open(output_path) as f:
        written = f.read()
    if '<div class="content">\n                \n            </div>' in written:
        print(f"  ERROR: Content div still empty for {slug}!")
    else:
        word_count = len(written.split())
        print(f"  OK: {word_count} words written to {output_path}")
        updated += 1

print(f"\nDone. Updated {updated}/{len(all_articles)} articles.")
