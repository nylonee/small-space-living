import json
articles = json.load(open('/home/nihal/content-site/articles/index.json'))
cats = {}
for a in articles:
    c = a['category']
    if c not in cats or a['date'] > cats[c]['date']:
        cats[c] = {'date': a['date'], 'slug': a['slug'], 'niche': a['niche_display']}
for c, info in sorted(cats.items(), key=lambda x: x[1]['date']):
    print(f"{info['date']} | {info['niche'][:25]:25s} | {c}")
