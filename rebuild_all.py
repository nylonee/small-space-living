#!/usr/bin/env python3
"""Rebuild all existing articles with current template, then deploy."""
import sys
sys.path.insert(0, '/home/nihal/content-site')
from generate import ContentGenerator

gen = ContentGenerator('/home/nihal/content-site/config.json')
print(f"Loaded {len(gen.articles)} articles from index")

for a in gen.articles:
    slug = a['slug']
    article_dir = gen.public_dir / slug
    article_html = gen.render_article_html(a)
    article_dir.mkdir(parents=True, exist_ok=True)
    with open(article_dir / 'index.html', 'w') as f:
        f.write(article_html)
    print(f"  ✓ /{slug}/ — {a.get('word_count', '?')} words")

# Rebuild static pages
gen._rebuild_static_pages()
print("✓ Static pages rebuilt")
