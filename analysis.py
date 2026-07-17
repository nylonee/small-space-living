#!/usr/bin/env python3
"""Full project analysis: compare sitemap, directories, metadata, and images."""
import os, re, json
from collections import defaultdict

DOCS = '/home/nihal/content-site/docs'
CONTENT = '/home/nihal/content-site/content/articles'

# 1. Parse sitemap
sitemap_path = os.path.join(DOCS, 'sitemap.xml')
sitemap = open(sitemap_path).read()
url_entries = re.findall(r'<loc>(.*?)</loc>', sitemap)
sitemap_slugs = set()
sitemap_timestamped = set()
sitemap_plain = set()
for url in url_entries:
    path = url.rstrip('/').rsplit('/', 1)[-1]
    sitemap_slugs.add(path)
    # Check if timestamped (has 8-digit date + optional time)
    if re.search(r'-\d{8}(-\d{4})?$', path):
        sitemap_timestamped.add(path)
    else:
        sitemap_plain.add(path)

print(f"=== SITEMAP ANALYSIS ===")
print(f"Total sitemap entries: {len(url_entries)}")
print(f"Unique slug paths in sitemap: {len(sitemap_slugs)}")
print(f"  Plain slugs (no timestamp): {len(sitemap_plain)}")
print(f"  Timestamped slugs: {len(sitemap_timestamped)}")

# 2. List all article dirs in docs/
article_dirs = []
for d in os.listdir(DOCS):
    dp = os.path.join(DOCS, d)
    if os.path.isdir(dp) and d not in ('categories', 'images', '.git', '.github'):
        article_dirs.append(d)

print(f"\n=== DIRECTORY ANALYSIS ===")
print(f"Total article-like directories: {len(article_dirs)}")

# Classify each dir
dir_timestamped = [d for d in article_dirs if re.search(r'-\d{8}(-\d{4})?$', d)]
dir_plain = [d for d in article_dirs if not re.search(r'-\d{8}(-\d{4})?$', d)]
print(f"  Plain-named dirs: {len(dir_plain)}")
print(f"  Timestamped dirs: {len(dir_timestamped)}")

# Generate stem (base slug without timestamp) for each dir
def get_stem(name):
    return re.sub(r'-\d{8}(-\d{4})?$', '', name)

dir_stems = defaultdict(list)
for d in article_dirs:
    stem = get_stem(d)
    dir_stems[stem].append(d)

print(f"  Unique article stems: {len(dir_stems)}")
multi = {k: v for k, v in dir_stems.items() if len(v) > 1}
print(f"  Stems with multiple versions: {len(multi)}")
if multi:
    sorted_multi = sorted(multi.items(), key=lambda x: -len(x[1]))
    print(f"  Top 5 multi-version stems:")
    for stem, versions in sorted_multi[:5]:
        print(f"    {stem}: {len(versions)} versions -> {versions}")

# 3. Cross-reference: which dirs are in the sitemap?
dirs_in_sitemap = [d for d in article_dirs if d in sitemap_slugs]
dirs_not_in_sitemap = [d for d in article_dirs if d not in sitemap_slugs]
print(f"\n  Dirs in sitemap: {len(dirs_in_sitemap)}")
print(f"  Dirs NOT in sitemap: {len(dirs_not_in_sitemap)}")

# For plain dirs: are they in sitemap?
plain_in_sitemap = [d for d in dir_plain if d in sitemap_slugs]
plain_not_in_sitemap = [d for d in dir_plain if d not in sitemap_slugs]
print(f"\n  Plain dirs in sitemap: {len(plain_in_sitemap)}")
print(f"  Plain dirs NOT in sitemap: {len(plain_not_in_sitemap)}")
if plain_not_in_sitemap:
    print(f"  Sample of plain dirs NOT in sitemap:")
    for d in sorted(plain_not_in_sitemap)[:10]:
        print(f"    - {d}")

# For timestamped dirs: are plain versions (stem) in sitemap?
# Also check if the timestamped dir itself is in sitemap
ts_in_sitemap = [d for d in dir_timestamped if d in sitemap_slugs]
ts_not_in_sitemap = [d for d in dir_timestamped if d not in sitemap_slugs]
print(f"\n  Timestamped dirs in sitemap: {len(ts_in_sitemap)}")
print(f"  Timestamped dirs NOT in sitemap: {len(ts_not_in_sitemap)}")

# For each timestamped dir NOT in sitemap, check if its stem (plain version) is
stems_of_ts_not_found = [get_stem(d) for d in ts_not_in_sitemap]
stem_parents = set(stems_of_ts_not_found)
print(f"  Unique stems of timestamped dirs NOT in sitemap: {len(stem_parents)}")
stem_parents_in_sitemap = stem_parents & sitemap_plain
stem_parents_not_in_sitemap = stem_parents - sitemap_plain
print(f"  ... whose plain stem IS in sitemap: {len(stem_parents_in_sitemap)}")
print(f"  ... whose plain stem is NOT in sitemap: {len(stem_parents_not_in_sitemap)}")

# 4. Check article markdown files
print(f"\n=== CONTENT ANALYSIS ===")
content_files = os.listdir(CONTENT) if os.path.isdir(CONTENT) else []
content_stems = set()
for f in content_files:
    if f.endswith('.md'):
        stem = get_stem(f.replace('.md', ''))
        content_stems.add(stem)
print(f"Content article files: {len([f for f in content_files if f.endswith('.md')])}")
print(f"Unique content stems: {len(content_stems)}")

# Content stems that have no matching dir at all
content_no_dir = []
for cs in content_stems:
    # Check if any dir starts with this stem
    found = any(d.startswith(cs) or cs.startswith(get_stem(d)) for d in article_dirs)
    if not found:
        content_no_dir.append(cs)
print(f"Content stems with NO matching directory: {len(content_no_dir)}")
if content_no_dir:
    for c in sorted(content_no_dir)[:10]:
        print(f"  - {c}")

# 5. Image analysis
print(f"\n=== IMAGE ANALYSIS ===")
images_dir = os.path.join(DOCS, 'images')
if os.path.isdir(images_dir):
    images = os.listdir(images_dir)
    print(f"Total images in docs/images/: {len(images)}")
else:
    print("docs/images/ does not exist")
    images = []

# Check for image references in content
print(f"\n=== SUMMARY ===")
print(f"Sitemap entries: {len(url_entries)}")
print(f"Article dirs: {len(article_dirs)}")
print(f"  - Plain: {len(dir_plain)}")
print(f"  - Timestamped: {len(dir_timestamped)}")
print(f"Unique article stems (content): {len(dir_stems)}")
print(f"Multi-version stems: {len(multi)}")
print(f"Dirs NOT in sitemap: {len(dirs_not_in_sitemap)}")
print(f"Content files: {len([f for f in content_files if f.endswith('.md')])}")
if 'images' in dir():
    print(f"Images: {len(images)}")

# Find plain dirs that are ALSO in sitemap as timestamped versions only
# (i.e., the plain dir is the LATEST, no timestamped version exists for it)
stems_as_ts_in_sitemap = set()
for ts_url in sitemap_timestamped:
    stems_as_ts_in_sitemap.add(get_stem(ts_url))

plain_dirs_with_no_ts_parent = [d for d in dir_plain 
                                 if d not in stems_as_ts_in_sitemap 
                                 and d not in sitemap_slugs]  # they ARE in sitemap

# Actually simpler: which plain dirs exist uniquely
print(f"\n=== DEDUP ANALYSIS ===")
# For stems with only 1 version
single_stems = [s for s, v in dir_stems.items() if len(v) == 1]
print(f"Stems with single directory version: {len(single_stems)}")

# Stems with 2+ versions
multi_stems = {s: v for s, v in dir_stems.items() if len(v) > 1}
# For each multi stem, which version(s) are in the sitemap?
for stem, versions in sorted(multi_stems.items(), key=lambda x: -len(x[1]))[:10]:
    in_sitemap = [v for v in versions if v in sitemap_slugs]
    not_in_sitemap = [v for v in versions if v not in sitemap_slugs]
    print(f"  '{stem}' ({len(versions)} versions): {len(in_sitemap)} in sitemap, {len(not_in_sitemap)} not")