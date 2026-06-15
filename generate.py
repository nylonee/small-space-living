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
        """Pick a random niche + category + format, rotating through categories fairly"""
        cfg = self.config
        
        # Count articles per category to track usage
        category_counts = {}
        if self.articles:
            for a in self.articles:
                c = a.get('category', '')
                category_counts[c] = category_counts.get(c, 0) + 1
        
        max_per = cfg.get('category_rotation', {}).get('max_per_category', 3)
        
        # Build candidate list: categories that haven't hit the limit
        candidates = []
        for nk, nv in cfg['niches'].items():
            for cat in nv['categories']:
                count = category_counts.get(cat, 0)
                if count >= max_per and max_per > 0:
                    continue
                candidates.append((nk, cat))
        
        if not candidates:
            # All categories exhausted — reset and allow any
            for nk, nv in cfg['niches'].items():
                for cat in nv['categories']:
                    candidates.append((nk, cat))
        
        # Shuffle and pick — pure randomness ensures fair distribution over time
        random.shuffle(candidates)
        niche_key, category = candidates[0]
        niche = cfg['niches'][niche_key]
        fmt = random.choice(cfg['article_formats'])
        return niche_key, niche, category, fmt
    
    def _products_for_category(self, category, niche_key=None):
        """Get real products from the database matching a category"""
        cfg = self.config
        if 'products' not in cfg:
            return []
        matched = []
        
        # 1. Exact match
        for p in cfg['products']:
            if category in p.get('categories', []):
                matched.append(p)
        
        # 2. Multi-word overlap (require 2+ significant words shared)
        if not matched:
            cat_words = set(category.lower().split())
            significant = {w for w in cat_words if len(w) >= 4}
            for p in cfg['products']:
                p_cats = [c.lower() for c in p.get('categories', [])]
                p_words = set()
                for pc in p_cats:
                    p_words.update(pc.split())
                p_sig = {w for w in p_words if len(w) >= 4}
                if len(significant & p_sig) >= 2:
                    matched.append(p)
        
        # 3. Same-niche fallback (not same-niche-all, only products with at least 1 word overlap)
        if not matched and niche_key:
            cat_words = set(category.lower().split())
            significant = {w for w in cat_words if len(w) >= 4}
            for p in cfg['products']:
                if niche_key in p.get('niches', []):
                    p_cats = [c.lower() for c in p.get('categories', [])]
                    p_words = set()
                    for pc in p_cats:
                        p_words.update(pc.split())
                    p_sig = {w for w in p_words if len(w) >= 4}
                    if significant & p_sig:
                        matched.append(p)
        
        return matched[:6]

    def _detect_category_from_content(self, markdown_text, niche_key):
        """Find the best-matching sub-category within a niche by scanning article content.
        Uses phrase matching (bi-grams) and word overlap scoring."""
        cfg = self.config
        niche = cfg.get('niches', {}).get(niche_key, {})
        best_cat = None
        best_score = 0
        body_lower = markdown_text.lower()
        for cat in niche.get('categories', []):
            cat_words = cat.lower().split()
            sig_words = {w for w in cat_words if len(w) >= 4}
            # Phrase bonus: check if bi-grams appear in the body
            phrase_bonus = 0
            for i in range(len(cat_words) - 1):
                bigram = cat_words[i] + ' ' + cat_words[i+1]
                if bigram in body_lower:
                    phrase_bonus += 2
            # Word matches
            word_score = sum(1 for w in sig_words if w in body_lower)
            total = word_score + phrase_bonus
            if total > best_score:
                best_score = total
                best_cat = cat
        return best_cat

    def build_prompt(self, category, fmt, niche_key=None):
        """Build the full prompt for Ollama"""
        year = datetime.datetime.now().year
        instruction = fmt['prompt_template'].format(category=category, year=year)
        
        # Get real products for this category and format as context
        products = self._products_for_category(category, niche_key)
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
- Use UK prices (£) not US prices ($) — this site targets UK readers via Amazon UK
- CRITICAL: DO NOT invent or make up product names. ONLY recommend products from the list provided below. If the list is empty, mention popular brands in the category without specific model numbers.
- CRITICAL: Target length MUST be 1000-1500 words. Write at least 1000 words.
- If the title says "Under £50" or similar, ONLY recommend products that genuinely cost under the stated price.
- If the title says "Under £100" or similar, ONLY recommend products that genuinely cost under the stated price.
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
    
    def _get_nous_api_key(self):
        """Read the Nous subscription API key from Hermes config.yaml."""
        import yaml
        hermes_config_path = os.path.expanduser("~/.hermes/config.yaml")
        try:
            with open(hermes_config_path) as f:
                hermes_cfg = yaml.safe_load(f)
            key = hermes_cfg.get("model", {}).get("api_key", "")
            if key:
                return key
        except Exception as e:
            print(f"  WARNING: Could not read Hermes API key: {e}")
        return ""

    def _parse_prompt_messages(self, prompt):
        """Parse the <|im_start|> format prompt into system/user message dicts."""
        system_match = re.search(
            r'<\|im_start\|>system\n(.*?)<\|im_end\|>', prompt, re.DOTALL
        )
        user_match = re.search(
            r'<\|im_start\|>user\n(.*?)<\|im_end\|>', prompt, re.DOTALL
        )
        messages = []
        if system_match:
            messages.append({"role": "system", "content": system_match.group(1).strip()})
        if user_match:
            messages.append({"role": "user", "content": user_match.group(1).strip()})
        if not messages:
            # Fallback: send the whole prompt as user message
            messages = [{"role": "user", "content": prompt}]
        return messages

    def _call_remote_llm(self, prompt):
        """Call DeepSeek Flash via OpenAI-compatible API (Nous inference)."""
        import requests

        remote_cfg = self.config.get("remote", {})
        api_key = self._get_nous_api_key()
        if not api_key:
            print("  ERROR: No Nous API key found in ~/.hermes/config.yaml")
            return ""

        messages = self._parse_prompt_messages(prompt)

        payload = {
            "model": remote_cfg.get("model", "deepseek/deepseek-v4-flash"),
            "messages": messages,
            "temperature": remote_cfg.get("temperature", 0.6),
            "max_tokens": remote_cfg.get("max_tokens", 4096),
            "stream": False,
        }

        response = requests.post(
            f"{remote_cfg['base_url'].rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def call_ollama(self, prompt):
        """Call local Ollama API."""
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

    def call_llm(self, prompt):
        """Dispatch to the configured LLM backend."""
        backend = self.config.get("backend", "ollama")
        if backend == "remote":
            return self._call_remote_llm(prompt)
        return self.call_ollama(prompt)
    
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
        prompt = self.build_prompt(category, fmt, niche_key)
        
        print(f"  Generating: {category} ({fmt['type']})...", flush=True)
        raw_text = self.call_llm(prompt)
        
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
        """Render article page HTML from template, with related articles"""
        template = self.jinja.get_template('article.html')
        
        # Find 3-4 related articles from the same niche, excluding the current one
        related = [
            a for a in self.articles
            if a['slug'] != article.get('slug') and a.get('niche_key') == article.get('niche_key')
        ]
        # Sort by date descending, take most recent 4
        related.sort(key=lambda a: a.get('date', ''), reverse=True)
        related_articles = related[:4]
        
        return template.render(
            site=self.config['site'],
            amazon=self.config['amazon'],
            article=article,
            related_articles=related_articles
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
        
        # Privacy page
        lines.append(f'  <url><loc>{site_url}{base_path}/privacy/</loc><priority>0.3</priority></url>')
        
        for article in self.articles:
            lines.append(
                f'  <url><loc>{site_url}{base_path}/{article["slug"]}/</loc>'
                f'<lastmod>{article["date"]}</lastmod><priority>0.6</priority></url>'
            )
        
        lines.append('</urlset>')
        return '\n'.join(lines)
    
    def render_privacy_html(self):
        """Render the privacy policy page"""
        template = self.jinja.get_template('privacy.html')
        return template.render(
            site=self.config['site']
        )
    
    def _rebuild_static_pages(self):
        """Rebuild homepage, category pages, privacy page, and sitemap"""
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
        
        # Privacy page
        privacy_dir = public / 'privacy'
        privacy_dir.mkdir(parents=True, exist_ok=True)
        with open(privacy_dir / 'index.html', 'w') as f:
            f.write(self.render_privacy_html())
        print("  → Privacy page rebuilt")
        
        # Sitemap
        with open(public / 'sitemap.xml', 'w') as f:
            f.write(self.render_sitemap())
        print(f"  → Sitemap generated")
    
    def publish_article(self, raw_markdown):
        """Process externally-generated markdown through the pipeline (affiliate injection, rendering, saving)."""
        if not raw_markdown or len(raw_markdown) < 100:
            print(f"  WARNING: Article too short ({len(raw_markdown) if raw_markdown else 0} chars), skipping")
            return None

        # Parse title
        title_match = re.search(r'^#\s+(.+)$', raw_markdown, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else "Untitled Article"
        title = re.sub(r'^"|"$', '', title)

        slug = slugify(title)
        date = datetime.datetime.now().strftime('%Y-%m-%d')
        excerpt = self.extract_excerpt(raw_markdown)
        html_content = self.markdown_to_html(raw_markdown)
        word_count = len(raw_markdown.split())

        # Try to detect category from content
        niche_key = None
        for nk, nv in self.config['niches'].items():
            for cat in nv['categories']:
                # Check the full article for the category's significant words
                cat_words = set(cat.lower().split())
                sig_words = {w for w in cat_words if len(w) >= 4}
                body_lower = raw_markdown.lower()
                matches = sum(1 for w in sig_words if w in body_lower)
                if matches >= 3:
                    niche_key = nk
                    break
            if niche_key:
                break
        if not niche_key:
            # Fallback: first-word check in first 500 chars (original heuristic)
            for nk, nv in self.config['niches'].items():
                for cat in nv['categories']:
                    first_word = cat.split()[0].lower()
                    if first_word in raw_markdown.lower()[:500]:
                        niche_key = nk
                        break
                if niche_key:
                    break
        if not niche_key:
            # Pick the least-used category
            from collections import Counter
            used = Counter(a.get('niche_key', 'budget_home_office') for a in self.articles)
            niche_key = min(self.config['niches'].keys(), key=lambda k: used.get(k, 0))

        niche = self.config['niches'].get(niche_key, {})

        # Detect the most specific sub-category from the article body
        detected_category = self._detect_category_from_content(raw_markdown, niche_key)
        if not detected_category and niche.get('categories'):
            detected_category = niche['categories'][0]

        tags = [niche.get('display_name', niche_key)]

        # Auto-detect format type from title
        title_lower = title.lower()
        if title_lower.startswith('how to choose'):
            fmt_type = 'buying_guide'
        elif title_lower.startswith('top ') and 'under' in title_lower:
            fmt_type = 'top_under'
        elif title_lower.startswith('the best') or title_lower.startswith('best '):
            fmt_type = 'best_of'
        else:
            fmt_type = 'buying_guide'

        # Post-process: inject affiliate links
        matched_products = self._inject_affiliate_products(html_content, detected_category, niche_key)
        html_content = matched_products['html']
        products = matched_products['products']

        article = {
            'slug': slug,
            'title': title,
            'date': date,
            'excerpt': excerpt,
            'niche_key': niche_key,
            'niche_display': niche.get('display_name', niche_key),
            'category': detected_category,
            'format_type': fmt_type,
            'word_count': word_count,
            'tags': tags,
            'html_content': html_content,
            'products': products
        }

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

        # Store in index (without html_content)
        index_entry = {k: v for k, v in article.items() if k != 'html_content'}
        self.articles.append(index_entry)

        self._save_index()
        self._rebuild_static_pages()

        print(f"\n✓ Published: /{article['slug']}/ — {article['word_count']} words ({niche.get('display_name', niche_key)})")
        return article

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
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    config_path = script_dir / 'config.json'
    generator = ContentGenerator(str(config_path))

    # Check for piped content
    import sys
    if '--stdin' in sys.argv and not sys.stdin.isatty():
        content = sys.stdin.read()
        generator.publish_article(content)
    elif '--content' in sys.argv:
        idx = sys.argv.index('--content')
        if idx + 1 < len(sys.argv):
            content = sys.argv[idx + 1]
            generator.publish_article(content)
        else:
            print("ERROR: --content requires a string argument")
            sys.exit(1)
    else:
        count = 1
        for arg in sys.argv[1:]:
            if arg.startswith('--'):
                continue
            try:
                count = int(arg)
                break
            except ValueError:
                continue
        generator.run(count)
