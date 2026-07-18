#!/usr/bin/env python3
"""Search IPTV-org for available FAST and target channels."""
import requests, re

url = "https://iptv-org.github.io/iptv/index.m3u"
resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
content = resp.text

patterns = [
    "pluto", "runtime", "canela", "vix", "filmrise",
    "disney junior", "cartoonito", "discovery kids",
    "discovery channel", "discovery science", "discovery turbo",
    "animal planet", "love nature", "curiosity", "smithsonian",
    "encuentro", "cnn en espa", "france 24 es", "dw espa",
    "euronews es", "cartoon network", "babyfirst", "dreamworks",
    "corazon", "cine real", "top cine", "dhe", "sony one",
    "telemundo", "nu9ve", "nueve", "a24 ", "c5n",
    "todo noticias", "cine sureno", "cine romantico",
    "cine terror", "snt", "telefuturo"
]

lines = content.split("\n")
for p in patterns:
    found = []
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF") and p in line.lower():
            in_q = False
            lc = -1
            for idx, c in enumerate(line):
                if c == '"':
                    in_q = not in_q
                elif c == ',' and not in_q:
                    lc = idx
            name = line[lc+1:].strip() if lc >= 0 else "?"
            j = i + 1
            while j < len(lines) and (lines[j].startswith("#") or not lines[j].strip()):
                j += 1
            url_line = lines[j].strip() if j < len(lines) else "?"
            found.append((name, url_line))
    if found:
        print(f"--- {p.upper()} ({len(found)} matches) ---")
        for name, u in found[:8]:
            print(f"  {name}  =>  {u[:90]}")
        if len(found) > 8:
            print(f"  ... and {len(found)-8} more")
        print()
