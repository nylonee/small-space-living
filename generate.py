#!/usr/bin/env python3
"""
Content generation pipeline for Small Space Living affiliate site.
Generates product review articles using local Ollama LLM.
Usage: python3 generate.py [num_articles]
"""

import json
import os
import sys
import re
import random
import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, BaseLoader

def slugify(text):
    """Convert text to URL-friendly slug"""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


class ContentGenerator:
    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.base_dir = self.config_path.parent
        
        with open(config_path) as f:
            self.config = json.load(f)
        
        cfg = self.config
        
        # Setup Jinja2
        self.jinja = Environment(loader=FileSystemLoader(str(self.base_dir / 'templates')))
        self.jinja.filters['slugify'] = slugify
        
        # Register custom filter to strip first <h1> from rendered content (avoids duplicate H1)
        def remove_first_h1(html):
            return re.sub(r'<h1>.*?</h1>', '', html, count=1, flags=re.DOTALL)
        self.jinja.filters['remove_first_h1'] = remove_first_h1
        
        # Setup paths
        self.articles_dir = Path(cfg['generation']['output_dir'])
        self.public_dir = Path(cfg['generation']['public_dir'])
        self.index_path = self.articles_dir / 'index.json'
        
        # Load article index
        self.articles = self._load_index()
        
        # Pre-compute slugified niche keys for consistent URLs
        self.niche_slugs = {nk: slugify(nk) for nk in cfg['niches']}
        # Map display name -> niche key for tag-based navigation
        self.display_to_niche = {v['display_name']: nk for nk, v in cfg['niches'].items()}
    
    def _load_index(self):
        if self.index_path.exists():
            with open(self.index_path) as f:
                return json.load(f)
        return []
    
    def _save_index(self):
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        with open(self.index_path, 'w') as f:
            json.dump(self.articles, f, indent=2)
    
    def pick_topic(self):
        """Pick a random niche + category + format, avoiding recent repeats"""
        cfg = self.config
        niche_keys = list(cfg['niches'].keys())
        
        # Prefer niches with fewer articles to keep things balanced
        if self.articles:
            niche_counts = {}
            for a in self.articles:
                niche_counts[a['niche_key']] = niche_counts.get(a['niche_key'], 0) + 1
            niche_keys.sort(key=lambda nk: niche_counts.get(nk, 0))
        
        niche_key = niche_keys[0] if niche_keys else list(cfg['niches'].keys())[0]
        niche = cfg['niches'][niche_key]
        category = random.choice(niche['categories'])
        fmt = random.choice(cfg['article_formats'])
        return niche_key, niche, category, fmt
    
    def _products_for_category(self, category):
        """Get real products from the database matching a category"""
        cfg = self.config
        if 'products' not in cfg:
            return []
        matched = []
        for p in cfg['products']:
            if category in p.get('categories', []):
                matched.append(p)
        # If no direct match, try broader: check if any category keywords overlap
        if not matched:
            cat_words = set(category.lower().split())
            for p in cfg['products']:
                p_cats = [c.lower() for c in p.get('categories', [])]
                p_words = set(' '.join(p_cats).split())
                if cat_words & p_words:  # any word overlap
                    matched.append(p)
        return matched[:6]  # cap at 6 to save context

    def build_prompt(self, category, fmt):
        """Build the full prompt for Ollama"""
        year = datetime.datetime.now().year
        instruction = fmt['prompt_template'].format(category=category, year=year)
        
        # Get real products for this category and format as context
        products = self._products_for_category(category)
        if products:
            product_hints = "\n".join(
                f"- {p['name']} — {p['description']}, around {p['price']}"
                for p in products
            )
            product_section = f"\nReal products you can reference in this article:\n{product_hints}\n"
        else:
            product_section = "\nMention real brand names and specific product names that are popular in this category.\n"
        
        prompt = f"""<|im_start|>system
You are an expert product reviewer for a website called "Small Space Living". You write detailed, helpful, SEO-optimized product review articles that help people with small apartments, tiny homes, and compact living spaces make informed purchasing decisions.

Guidelines:
- Write in natural, conversational English
- Use markdown formatting (## for headers, **bold** for emphasis)
- Mention real product names and brand names when making recommendations
- Every product mention must include: what it is, why it works for small spaces, approximate price range
- Be specific and helpful - this is for real readers
- DO use realistic price ranges (e.g. "typically $30-$50")
- CRITICAL: Target length MUST be 1000-1500 words. Write at least 1000 words.
- If the title says "Under $50", ONLY recommend products that genuinely cost under $50. Do NOT include products over that price.
- If the title says "Under $100", ONLY recommend products that genuinely cost under $100.
{product_section}
START YOUR RESPONSE with the article title as a single H1 markdown heading, like this:
# Your Actual Article Title Here
Then immediately follow with the article content. Do not include any preamble or explanation before the title.
|<|im_end|>
|<|im_start|>user
{instruction}
|<|im_end|>
|<|im_start|>assistant
"""
        return prompt
    
    def call_ollama(self, prompt):
        """Call Ollama API with streaming-style non-streaming"""
        import requests
        
        payload = {
            'model': self.config['ollama']['model'],
            'prompt': prompt,
            'stream': False,
            'temperature': self.config['ollama'].get('temperature', 0.7),
            'options': {
                'num_predict': self.config['ollama'].get('max_tokens', 2048),
                'num_ctx': self.config['ollama'].get('num_ctx', 4096)
            }
        }
        
        response = requests.post(
            self.config['ollama']['url'],
            json=payload,
            timeout=300
        )
        response.raise_for_status()
        return response.json()['response']
    
    def markdown_to_html(self, md_text):
        """Convert markdown to HTML"""
        import markdown as md_lib
        return md_lib.markdown(md_text, extensions=['extra', 'nl2br', 'sane_lists'])
    
    def extract_excerpt(self, text):
        """Extract first substantial paragraph from markdown as excerpt"""
        lines = text.split('\n')
        in_paragraph = False
        para_buf = []
        
        for line in lines:
            stripped = line.strip()
            # Skip headers, empty lines, and very short lines
            if not stripped:
                if in_paragraph and para_buf:
                    excerpt = ' '.join(para_buf).strip()
                    if len(excerpt) > 40:
                        return excerpt[:300]
                    para_buf = []
                    in_paragraph = False
                continue
            if stripped.startswith('#'):
                continue
            if stripped.startswith(('*', '-', '1.', '**')):
                continue
            
            in_paragraph = True
            # Remove markdown formatting
            clean = re.sub(r'[*_~`]', '', stripped)
            para_buf.append(clean)
        
        if para_buf:
            excerpt = ' '.join(para_buf).strip()
            if len(excerpt) > 40:
                return excerpt[:300]
        
        return text[:200].strip()
    
    def generate_article(self):
        """Generate one complete article by calling Ollama"""
        niche_key, niche, category, fmt = self.pick_topic()
        prompt = self.build_prompt(category, fmt)
        
        print(f"  Generating: {category} ({fmt['type']})...", flush=True)
        raw_text = self.call_ollama(prompt)
        
        if not raw_text or len(raw_text) < 100:
            print(f"  WARNING: Short response ({len(raw_text) if raw_text else 0} chars), skipping")
            return None
        
        # Parse title
        title_match = re.search(r'^#\s+(.+)$', raw_text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else f"Best {category} for Small Spaces"
        # Clean common title artifacts
        title = re.sub(r'^"|"$', '', title)
        
        slug = slugify(title)
        date = datetime.datetime.now().strftime('%Y-%m-%d')
        excerpt = self.extract_excerpt(raw_text)
        html_content = self.markdown_to_html(raw_text)
        word_count = len(raw_text.split())
        
        # Tags = category groups
        tags = [niche['display_name']]
        
        # Post-process: inject affiliate links and find matched products
        matched_products = self._inject_affiliate_products(html_content, category, niche_key)
        html_content = matched_products['html']
        products = matched_products['products']
        
        return {
            'slug': slug,
            'title': title,
            'date': date,
            'excerpt': excerpt,
            'niche_key': niche_key,
            'niche_display': niche['display_name'],
            'category': category,
            'format_type': fmt['type'],
            'word_count': word_count,
            'tags': tags,
            'html_content': html_content,
            'products': products
        }
    
    def _inject_affiliate_products(self, html_content, category, niche_key):
        """Post-process HTML: turn product mentions into affiliate links + add product cards"""
        cfg = self.config
        tag = cfg['amazon']['tag']
        base_url = cfg['amazon']['base_url']
        all_products = cfg.get('products', [])
        
        # Get products matching this category exactly
        cat_products = [p for p in all_products if category in p.get('categories', [])]
        
        # Fallback: require 2+ shared words AND same niche
        if not cat_products:
            cat_words = set(w for w in category.lower().split() if len(w) > 3)
            for p in all_products:
                niche_match = niche_key in p.get('niches', [])
                for p_cat in p.get('categories', []):
                    p_words = set(w for w in p_cat.lower().split() if len(w) > 3)
                    shared = cat_words & p_words
                    if niche_match and len(shared) >= 2:
                        cat_products.append(p)
                        break
        
        # If still nothing, grab any products from the same niche (up to 4)
        if not cat_products:
            niche_products = [p for p in all_products if niche_key in p.get('niches', [])]
            cat_products = niche_products[:4]
        
        # Deduplicate by ASIN
        seen = set()
        unique_products = []
        for p in cat_products:
            if p['asin'] not in seen:
                seen.add(p['asin'])
                unique_products.append(p)
        
        # Turn product name/brand mentions into affiliate links
        # Strategy: match only brand names + specific product names (not generic terms)
        html = html_content
        linked_asins = set()
        
        # Collect all candidate matches from brand names and product names
        candidates = []
        for p in unique_products:
            # Only try brand name and exact product name as keywords
            names_to_match = list(set([p['brand'], p['name']]))
            for keyword in names_to_match:
                if len(keyword) < 3:
                    continue
                for m in re.finditer(re.escape(keyword), html, re.IGNORECASE):
                    candidates.append((m.start(), m.end(), keyword, p['asin']))
        
        # Sort by position descending (end-to-start to avoid position shifting)
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        # Tag existing link positions
        link_ranges = set()
        for m in re.finditer(r'<a\s[^>]*>.*?</a>', html, re.DOTALL):
            link_ranges.add((m.start(), m.end()))
        
        def overlaps_link(start, end):
            for ls, le in link_ranges:
                if start < le and end > ls:
                    return True
            return False
        
        for orig_start, orig_end, keyword, asin in candidates:
            # Process end-to-start: replacements only affect text AFTER current position,
            # so remaining lower-position candidates are unaffected — no offset needed
            if overlaps_link(orig_start, orig_end):
                continue
            if html[orig_start:orig_end].lower() != keyword.lower():
                continue
            affiliate_url = f"{base_url}/{asin}?tag={tag}"
            link_html = f'<a href="{affiliate_url}" rel="nofollow sponsored" target="_blank">{html[orig_start:orig_end]}</a>'
            html = html[:orig_start] + link_html + html[orig_end:]
            linked_asins.add(asin)
            # Update link_ranges to include new link
            link_ranges.add((orig_start, orig_start + len(link_html)))
        
        # Select up to 4 products for the recommendation grid
        # Prioritize mentioned products, then fill with non-mentioned
        grid_products = []
        grid_asins = set()
        
        for p in unique_products:
            if len(grid_products) >= 4:
                break
            if p['asin'] in linked_asins:
                grid_products.append(p)
                grid_asins.add(p['asin'])
        
        if len(grid_products) < 4:
            for p in unique_products:
                if len(grid_products) >= 4:
                    break
                if p['asin'] not in grid_asins:
                    grid_products.append(p)
                    grid_asins.add(p['asin'])
        
        # Cap at 4 products
        grid_products = grid_products[:4]
        
        return {'html': html, 'products': grid_products}

    def render_article_html(self, article):
        """Render article page HTML from template"""
        template = self.jinja.get_template('article.html')
        return template.render(
            site=self.config['site'],
            amazon=self.config['amazon'],
            article=article
        )
    
    def render_index_html(self):
        """Render homepage from template"""
        sorted_articles = sorted(self.articles, key=lambda a: a['date'], reverse=True)
        
        # Build categories dict with counts, keyed by slug
        categories = {}
        for nk, ns in self.niche_slugs.items():
            count = sum(1 for a in self.articles if a['niche_key'] == nk)
            categories[ns] = {
                'display_name': self.config['niches'][nk]['display_name'],
                'description': self.config['niches'][nk]['description'],
                'count': count
            }
        
        template = self.jinja.get_template('index.html')
        return template.render(
            site=self.config['site'],
            articles=sorted_articles[:24],
            categories=categories
        )
    
    def render_category_html(self, niche_key):
        """Render a category page"""
        niche = self.config['niches'][niche_key]
        cat_articles = [a for a in self.articles if a['niche_key'] == niche_key]
        cat_articles.sort(key=lambda a: a['date'], reverse=True)
        
        template = self.jinja.get_template('category.html')
        return template.render(
            site=self.config['site'],
            category_name=niche['display_name'],
            category_description=niche['description'],
            articles=cat_articles
        )
    
    def render_sitemap(self):
        """Generate sitemap.xml"""
        site_url = self.config['site']['url'].rstrip('/')
        base_path = self.config['site'].get('base_path', '')
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            f'  <url><loc>{site_url}{base_path}/</loc><priority>1.0</priority></url>'
        ]
        
        for ns in self.niche_slugs.values():
            lines.append(f'  <url><loc>{site_url}{base_path}/categories/{ns}/</loc><priority>0.8</priority></url>')
        
        for article in self.articles:
            lines.append(
                f'  <url><loc>{site_url}{base_path}/{article["slug"]}/</loc>'
                f'<lastmod>{article["date"]}</lastmod><priority>0.6</priority></url>'
            )
        
        lines.append('</urlset>')
        return '\n'.join(lines)
    
    def _rebuild_static_pages(self):
        """Rebuild homepage, category pages, and sitemap"""
        public = self.public_dir
        public.mkdir(parents=True, exist_ok=True)
        
        # Homepage
        with open(public / 'index.html', 'w') as f:
            f.write(self.render_index_html())
        print(f"  → Homepage rebuilt ({len(self.articles)} articles indexed)")
        
        # Category pages
        for niche_key in self.config['niches']:
            ns = self.niche_slugs[niche_key]
            cat_dir = public / 'categories' / ns
            cat_dir.mkdir(parents=True, exist_ok=True)
            with open(cat_dir / 'index.html', 'w') as f:
                f.write(self.render_category_html(niche_key))
        print(f"  → Category pages rebuilt ({len(self.config['niches'])} categories)")
        
        # Sitemap
        with open(public / 'sitemap.xml', 'w') as f:
            f.write(self.render_sitemap())
        print(f"  → Sitemap generated")
    
    def run(self, count=3):
        """Generate `count` articles and rebuild site"""
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        self.public_dir.mkdir(parents=True, exist_ok=True)
        
        generated = 0
        for i in range(count):
            print(f"\n--- Article {i+1}/{count} ---")
            
            try:
                article = self.generate_article()
            except Exception as e:
                print(f"  ERROR: {e}")
                continue
            
            if article is None:
                continue
            
            # Deduplicate slug
            existing_slugs = {a['slug'] for a in self.articles}
            if article['slug'] in existing_slugs:
                article['slug'] = f"{article['slug']}-{datetime.datetime.now().strftime('%Y%m%d-%H%M')}"
            
            # Save article HTML
            article_dir = self.public_dir / article['slug']
            article_dir.mkdir(parents=True, exist_ok=True)
            article_html = self.render_article_html(article)
            with open(article_dir / 'index.html', 'w') as f:
                f.write(article_html)
            
            # Store in index (without html_content to keep index small)
            index_entry = {k: v for k, v in article.items() if k != 'html_content'}
            self.articles.append(index_entry)
            
            print(f"  ✓ /{article['slug']}/ — {article['word_count']} words")
            generated += 1
        
        # Always rebuild static pages, even if no new articles
        # (config/template changes still need to propagate)
        if generated == 0 and count > 0:
            print("\n✗ No articles generated. Something went wrong.")
            return
        
        self._save_index()
        self._rebuild_static_pages()
        
        if generated == 0:
            print(f"\n✓ Static pages rebuilt. Total: {len(self.articles)} articles.")
        else:
            print(f"\n✓ Done! {generated} new articles. Total: {len(self.articles)} articles.")
        print(f"  Site files: {self.public_dir}")


if __name__ == '__main__':
    # Default: 3 articles per run
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    config_path = script_dir / 'config.json'
    
    generator = ContentGenerator(str(config_path))
    generator.run(count)
