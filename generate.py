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
    
    def build_prompt(self, category, fmt):
        """Build the full prompt for Ollama"""
        year = datetime.datetime.now().year
        instruction = fmt['prompt_template'].format(category=category, year=year)
        
        prompt = f"""<|im_start|>system
You are an expert product reviewer for a website called "Small Space Living". You write detailed, helpful, SEO-optimized product review articles that help people with small apartments, tiny homes, and compact living spaces make informed purchasing decisions.

Guidelines:
- Write in natural, conversational English
- Use markdown formatting (## for headers, **bold** for emphasis)
- Include realistic product names and approximate price ranges
- Every product mention must include: what it is, why it works for small spaces, approximate price range
- Be specific and helpful - this is for real readers
- DO NOT fabricate brand names for well-known products (use "a popular brand" or generic descriptions)
- DO use realistic price ranges (e.g. "typically $30-$50")
- Target length: 800-1500 words
START YOUR RESPONSE with the article title as a single H1 markdown heading, like this:
# Your Actual Article Title Here
Then immediately follow with the article content. Do not include any preamble or explanation before the title.
|<|im_end|>
<|im_start|>user
{instruction}
|<|im_end|>
<|im_start|>assistant
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
        
        return {
            'slug': slug,
            'title': title,
            'date': date,
            'excerpt': excerpt,
            'niche_key': niche_key,
            'category': category,
            'format_type': fmt['type'],
            'word_count': word_count,
            'tags': tags,
            'html_content': html_content
        }
    
    def render_article_html(self, article):
        """Render article page HTML from template"""
        template = self.jinja.get_template('article.html')
        return template.render(
            site=self.config['site'],
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
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            f'  <url><loc>{site_url}/</loc><priority>1.0</priority></url>'
        ]
        
        for ns in self.niche_slugs.values():
            lines.append(f'  <url><loc>{site_url}/categories/{ns}/</loc><priority>0.8</priority></url>')
        
        for article in self.articles:
            lines.append(
                f'  <url><loc>{site_url}/{article["slug"]}/</loc>'
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
        
        if generated == 0:
            print("\n✗ No articles generated. Something went wrong.")
            return
        
        self._save_index()
        self._rebuild_static_pages()
        
        print(f"\n✓ Done! {generated} new articles. Total: {len(self.articles)} articles.")
        print(f"  Site files: {self.public_dir}")


if __name__ == '__main__':
    # Default: 3 articles per run
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    config_path = script_dir / 'config.json'
    
    generator = ContentGenerator(str(config_path))
    generator.run(count)
