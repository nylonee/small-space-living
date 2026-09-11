import re

text = open('/home/nihal/content-site/_article.md').read()
# Strip markdown headings, links, bold, list markers
text = re.sub(r'^#{1,6}\s+', '', text, flags=re.M)
text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
text = re.sub(r'[*_>`#]', '', text)
words = [w for w in re.findall(r"[A-Za-z0-9£'\-]+", text) if re.search(r'[A-Za-z0-9]', w)]
print('clean prose words:', len(words))
