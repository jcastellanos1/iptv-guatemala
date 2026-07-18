#!/usr/bin/env python3
"""Search for Pluto TV Spanish-language channels in IPTV-org."""
import requests, re, sys
sys.stdout.reconfigure(encoding='utf-8')

url = "https://iptv-org.github.io/iptv/index.m3u"
resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
content = resp.text

lines = content.split("\n")
results = []

spanish_keywords = ["latino", "latina", "espanol", "español", "spanish", "cine", "novela", "telenovela",
                     "series", "pelicul", "comedia", "terror", "familia", "drama", "suspenso", "romance",
                     "sci-fi", "clasico", "clásico", "estelar", "accion", "acción", "kids", "junior",
                     "nick", "cartoon", "discovery", "animal", "history", "nat geo", "national geo"]

for i, line in enumerate(lines):
    if not line.startswith("#EXTINF"):
        continue
    ll = line.lower()
    if "pluto" not in ll:
        continue
    # Extract tvg-id
    tvg_match = re.search(r'tvg-id="([^"]*)"', line)
    tvg_id = tvg_match.group(1) if tvg_match else ""
    # Extract display name
    in_q = False
    lc = -1
    for idx, c in enumerate(line):
        if c == '"':
            in_q = not in_q
        elif c == ',' and not in_q:
            lc = idx
    name = line[lc+1:].strip() if lc >= 0 else "?"
    # Get URL
    j = i + 1
    while j < len(lines) and (lines[j].startswith("#") or not lines[j].strip()):
        j += 1
    url_line = lines[j].strip() if j < len(lines) else "?"

    # Filter for Spanish content
    name_lower = name.lower()
    id_lower = tvg_id.lower()
    has_spanish = any(k in name_lower or k in id_lower for k in spanish_keywords)
    has_latam_suffix = any(s in id_lower for s in [".mx", ".ar", ".co", ".la", ".pe", ".cl", ".ve"])

    if has_spanish or has_latam_suffix:
        results.append((name, tvg_id, url_line))

print(f"Found {len(results)} Spanish Pluto TV channels:\n")
for name, tvg_id, u in sorted(results, key=lambda x: x[0]):
    print(f"  {name} | {tvg_id} | {u[:85]}")
