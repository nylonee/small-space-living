#!/usr/bin/env python3
"""Fix the mis-categorized article's HTML and rebuild the site."""
import json, re, sys
from pathlib import Path

BASE = Path('/home/nihal/content-site')
CONFIG_PATH = BASE / 'config.json'

with open(CONFIG_PATH) as f:
    config = json.load(f)

# Import the generator
sys.path.insert(0, str(BASE))
from generate import ContentGenerator, slugify as make_slug

generator = ContentGenerator(str(CONFIG_PATH))

# Read the original markdown
with open(BASE / '_article.md') as f:
    markdown = f.read()

# Parse title
title_match = re.search(r'^#\s+(.+)$', markdown, re.MULTILINE)
title = title_match.group(1).strip() if title_match else "Untitled Article"
title = re.sub(r'^"|"$', '', title)

slug = make_slug(title)
date = '2026-11-20'
excerpt = generator.extract_excerpt(markdown)
html_content = generator.markdown_to_html(markdown)
word_count = len(markdown.split())

# Force the correct niche and category
niche_key = 'apartment_organization'
detected_category = 'closet organizers for small closets'
niche = config['niches'][niche_key]
tags = ['Apartment Organization']

print(f"Regenerating: {slug}")
print(f"  Niche: {niche_key} ({niche['display_name']})")
print(f"  Category: {detected_category}")

# Now inject the correct affiliate products
matched_products = generator._inject_affiliate_products(html_content, detected_category, niche_key)
html_content = matched_products['html']
products = matched_products['products']

print(f"  Matched {len(products)} products for affiliate linking")

article = {
    'slug': slug,
    'title': title,
    'date': date,
    'excerpt': excerpt,
    'niche_key': niche_key,
    'niche_display': niche['display_name'],
    'category': detected_category,
    'format_type': 'best_of',
    'word_count': word_count,
    'tags': tags,
    'products': products,
    'html_content': html_content,
}

# Render and save the article HTML
article_html = generator.render_article_html(article)
article_dir = BASE / 'docs' / slug
article_dir.mkdir(parents=True, exist_ok=True)
with open(article_dir / 'index.html', 'w') as f:
    f.write(article_html)
print(f"  ✓ HTML written to docs/{slug}/index.html")

# Update the index entry (replace existing or append)
with open(BASE / 'articles/index.json') as f:
    all_articles = json.load(f)

found = False
for i, a in enumerate(all_articles):
    if a.get('slug') == slug:
        all_articles[i] = {k: v for k, v in article.items() if k != 'html_content'}
        all_articles[i]['products'] = products  # keep products in index
        found = True
        print(f"  ✓ Updated index entry at position {i}")
        break

if not found:
    all_articles.append({k: v for k, v in article.items() if k != 'html_content'})
    print(f"  ✓ Added new index entry (position {len(all_articles)-1})")

with open(BASE / 'articles/index.json', 'w') as f:
    json.dump(all_articles, f, indent=2)

# Rebuild static pages (homepage, categories, sitemap)
generator.articles = all_articles
generator._rebuild_static_pages()

print("\n✓ Fix complete. Ready to deploy.")