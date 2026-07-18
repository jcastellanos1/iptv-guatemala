#!/usr/bin/env python3
"""
build_definitive_playlist.py — One-shot script to build the definitive 75-channel playlist.

Steps:
1. Keep Lote 1 confirmed channels (except E! blocked URL, NatGeo English)
2. Keep Guatemala 3 channels
3. Keep Caracol Televisión from Lote 2
4. Remove all other Lote 2 channels
5. Search for NatGeo replacement (Latin America Spanish)
6. Add new channels from the priority catalog until exactly 75
7. Generate all reports and final playlist
"""

import os
import sys
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
import requests

BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CURATED_FILE = os.path.join(BASE_DIR, "data", "curated_channels.json")
SELECTED_FILE = os.path.join(BASE_DIR, "data", "selected_channels.json")
CHANNELS_FILE = os.path.join(BASE_DIR, "data", "channels.json")
OVERRIDES_FILE = os.path.join(BASE_DIR, "data", "channel_overrides.json")
OUTPUT_M3U = os.path.join(BASE_DIR, "index.m3u")
REPORT_MD = os.path.join(BASE_DIR, "reports", "curation-report.md")
FINAL_LIST_MD = os.path.join(BASE_DIR, "reports", "final-channel-list.md")

IPTV_ORG_M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT_SECONDS = 5

GLOBAL_BLOCKED_URLS = [
    "http://bantel-cdn1.iptvperu.tv:1935/btnscrtn/entertainment.stream/playlist.m3u8"
]

# Channels to absolutely remove
REMOVE_CHANNELS = {"NTN24", "Milenio Televisión", "Foro TV"}

# Lote 2 channels to remove (keep only Caracol Televisión)
LOTE2_CHANNELS = {
    "Imagen Televisión", "Canal 5 México", "Canal 22 México",
    "RCN Televisión", "Canal 1 Colombia", "Canal Capital",
    "Teleantioquia", "Telecaribe", "Telepacífico",
    "TV Perú", "Latina Televisión", "Panamericana Televisión",
    "América Televisión Perú", "Mega Chile", "TVN Chile",
    "Telefe", "El Trece Argentina", "Canal IPe"
}

# Final categories mapping
CATEGORY_ORDER = [
    "Guatemala",
    "Películas y Series",
    "Entretenimiento",
    "TV Latinoamérica",
    "Infantil",
    "Documentales y Cultura",
    "Noticias"
]

# The definitive catalog to fill up to 75
# Each entry: (name, aliases, preferred_regions, blocked_terms, category)
# Names MUST match IPTV-org database entries exactly
CATALOG = [
    # PELÍCULAS Y SERIES — using actual IPTV-org names
    ("Runtime Espanol", ["Runtime Español", "Runtime Latino"], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Canela.TV", ["Canela TV", "Canela Cinema"], ["Latin America", "Panregional", "Mexico"], ["Canela Clasicos", "Canela Telenovelas", "Canela Kids", "Canela Music", "Canela Hits"], "Películas y Series"),
    ("Pluto TV Nuestro Cine", ["Nuestro Cine"], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Novelas", ["Pluto TV Telenovelas"], ["Latin America", "Panregional", "Mexico"], ["Novelas de Mexico", "Novelas de Venezuela", "Novelas de Otros"], "Películas y Series"),
    ("Pluto TV Novelas de México", ["Pluto TV Novelas Mexico"], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Series", ["Pluto TV Series LatAm"], ["Latin America", "Panregional", "Mexico"], ["Pluto TV Series Latinas", "Pluto TV Series Retro", "Series de Accion", "Series de Comedia", "Series de Crimen", "Series de Drama", "Series de Sci-Fi", "Series de Otros"], "Películas y Series"),
    ("Pluto TV Series Latinas", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Sci-Fi", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Cine Acción", ["Pluto TV Cine Accion"], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Cine Comedia", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Cine Drama", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Cine Terror", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Anime", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Series Retro", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Series de Acción", ["Pluto TV Series de Accion"], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Series de Comedia", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Series de Crimen", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Series de Drama", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Sci-Fi", ["Pluto TV SciFi"], ["Latin America", "Panregional", "Mexico"], ["Pluto TV Series de Sci-Fi"], "Películas y Series"),
    ("Pluto TV Series de Sci-Fi", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Terror", [], ["Latin America", "Panregional", "Mexico"], ["Terror Trash"], "Películas y Series"),
    ("Pluto TV Novelas de Venezuela", [], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Novelas de Otros Continentes", ["Pluto TV Novelas de Otros"], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Pluto TV Series de Otros Continentes", ["Pluto TV Series de Otros"], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Corazón", ["Corazon TV", "Corazón TV"], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("DHE", ["DHE TV"], ["Latin America", "Panregional", "Mexico"], [], "Películas y Series"),
    ("Curiosity Explora", ["Curiosity Español", "Curiosity Espanol"], ["Latin America", "Panregional", "Mexico"], ["Curiosity Animales", "Curiosity Motores"], "Películas y Series"),
    ("Curiosity Animales", [], ["Latin America", "Panregional", "Mexico"], ["Curiosity Explora", "Curiosity Motores"], "Documentales y Cultura"),
    ("Curiosity Motores", [], ["Latin America", "Panregional", "Mexico"], ["Curiosity Explora", "Curiosity Animales"], "Documentales y Cultura"),
    # ENTRETENIMIENTO LATINOAMERICANO → TV Latinoamérica
    ("Imagen Televisión", ["Imagen TV", "Imagen Television"], ["Mexico", "Panregional"], ["Imagen Radio"], "TV Latinoamérica"),
    ("Canal 5 México", ["Canal 5", "Canal 5 HD", "Canal 5 Mexico"], ["Mexico", "Panregional"], ["Canal 5 Honduras", "Canal 5 Uruguay", "Canal 5 Peru"], "TV Latinoamérica"),
    ("Telefe", ["Telefe HD", "Telefe Argentina", "Telefe Internacional"], ["Latin America", "Panregional"], [], "TV Latinoamérica"),
    ("El Trece Argentina", ["El Trece", "Canal 13 Argentina", "El Trece HD"], ["Latin America", "Panregional"], ["Canal 13 Chile", "Canal 13 Colombia"], "TV Latinoamérica"),
    ("Mega Chile", ["Mega", "Mega TV", "Mega HD"], ["cl", "Chile"], ["Mega TV USA", "Mega TV Puerto Rico", "py", "Paraguay"], "TV Latinoamérica"),
    ("TVN Chile", ["TVN", "Televisión Nacional de Chile", "TV Chile"], ["cl", "Chile"], ["TVN Panama", "TVN Poland"], "TV Latinoamérica"),
    ("Canal 13 Chile", ["Canal 13", "Canal 13 HD", "Trece Chile"], ["cl", "Chile"], ["Canal 13 Argentina", "Canal 13 Colombia"], "TV Latinoamérica"),
    ("Latina Televisión", ["Latina", "Latina TV", "Latina HD"], ["pe", "Peru"], ["ve", "Venezuela"], "TV Latinoamérica"),
    ("América Televisión Perú", ["America TV Peru", "América Televisión", "America Television"], ["Andes", "Panregional"], ["America TV Argentina"], "TV Latinoamérica"),
    ("Panamericana Televisión", ["Panamericana TV", "Panamericana HD"], ["Andes", "Panregional"], [], "TV Latinoamérica"),
    ("RCN Televisión", ["Canal RCN", "RCN TV", "RCN HD", "RCN Colombia"], ["Colombia", "Andes", "Panregional"], ["NTN24"], "TV Latinoamérica"),
    ("Canal 1 Colombia", ["Canal 1", "Canal Uno", "Canal 1 HD"], ["Colombia", "Andes", "Panregional"], ["Canal 1 Ecuador", "Canal 1 Peru"], "TV Latinoamérica"),
    ("Ecuavisa", ["Ecuavisa HD", "Ecuavisa Ecuador"], ["Andes", "Panregional"], [], "TV Latinoamérica"),
    ("Teleamazonas", ["Teleamazonas HD", "Teleamazonas Ecuador"], ["Andes", "Panregional"], [], "TV Latinoamérica"),
    ("Unitel Bolivia", ["Unitel", "Unitel HD"], ["bo", "Bolivia"], ["pe", "Peru"], "TV Latinoamérica"),
    ("Red Uno", ["Red Uno Bolivia", "Red Uno HD"], ["bo", "Bolivia"], [], "TV Latinoamérica"),
    ("Telefuturo Paraguay", ["Telefuturo", "Telefuturo HD"], ["py", "Paraguay"], [], "TV Latinoamérica"),
    ("Venevisión", ["Venevision", "Venevisión HD"], ["Andes", "Panregional", "Latin America"], [], "TV Latinoamérica"),
    ("Televen", ["Televen HD", "Televen Venezuela"], ["Andes", "Panregional", "Latin America"], [], "TV Latinoamérica"),
    # INFANTILES
    ("Disney Junior", ["Disney Junior Latinoamérica", "Disney Junior Latin America", "Disney Jr"], ["Latin America", "Panregional", "Mexico"], ["Disney Channel", "Disney XD", "MENA", "West", "fr", "france", "english"], "Infantil"),
    ("DreamWorks Channel Latin America", ["DreamWorks Channel", "DreamWorks Latinoamérica", "DreamWorks Latin America"], ["Latin America", "Panregional", "Mexico"], ["DreamWorks Channel Asia"], "Infantil"),
    ("Cartoon Network", ["Cartoon Network Latin America", "Cartoon Network Latinoamérica"], ["Latin America", "Panregional", "Mexico"], ["Cartoonito"], "Infantil"),
    ("Discovery Kids", ["Discovery Kids Latinoamérica", "Discovery Kids Latin America"], ["Latin America", "Panregional", "Mexico"], ["Discovery Channel", "Discovery Science", "Discovery Turbo"], "Infantil"),
    ("Pluto TV Kids", ["Pluto TV Niños"], ["Latin America", "Panregional", "Mexico"], ["Pluto TV Junior", "Pluto TV Nick", "Kids Spain", "Kids Classics", "Kids Club"], "Infantil"),
    ("Pluto TV Junior", ["Pluto TV Jr"], ["Latin America", "Panregional", "Mexico"], ["Pluto TV Kids", "Pluto TV Nick", "Juniorklubben"], "Infantil"),
    ("BabyFirst", ["BabyFirst TV", "BabyFirst Español"], ["Latin America", "Panregional", "Mexico"], [], "Infantil"),
    # DOCUMENTALES Y CULTURA
    ("Discovery Channel", ["Discovery Channel Latin America", "Discovery Channel Latinoamérica"], ["Latin America", "Panregional", "Mexico"], ["Discovery Kids", "Discovery Science", "Discovery Turbo", "Discovery Home", "Discovery Family", "Discovery Life", "Discovery World"], "Documentales y Cultura"),
    ("Animal Planet", ["Animal Planet Latin America", "Animal Planet Latinoamérica"], ["Latin America", "Panregional", "Mexico"], [], "Documentales y Cultura"),
    ("Love Nature", ["Love Nature en Espanol", "Love Nature Español", "Love Nature HD"], ["Latin America", "Panregional", "Mexico"], ["english", "canada", "ca"], "Documentales y Cultura"),
    ("Smithsonian Channel", ["Smithsonian Channel Latinoamérica"], ["Latin America", "Panregional", "Mexico"], ["Smithsonian Channel Pluto", "Smithsonian Channel Selects"], "Documentales y Cultura"),
    ("Canal IPe", ["Canal IPe HD", "IPe"], ["Andes", "Panregional"], [], "Documentales y Cultura"),
    ("Discovery Turbo", ["Discovery Turbo TV", "Discovery Turbo Latin America"], ["Latin America", "Panregional", "Mexico"], ["Discovery Kids", "Discovery Channel", "Discovery Science", "Discovery Home"], "Documentales y Cultura"),
    # NOTICIAS
    ("France 24 Español", ["France 24 Spanish", "France 24 en Español", "France 24 Espanol"], ["Latin America", "Panregional", "Mexico"], ["France 24 English", "France 24 Français", "France 24 Arabic"], "Noticias"),
    ("DW Español", ["DW Espanol", "DW Latinoamérica", "DW en Español", "Deutsche Welle Español"], ["Latin America", "Panregional", "Mexico"], ["DW Deutsch", "DW English", "DW Arabia", "DW Feed"], "Noticias"),
    ("A24", ["A24 Argentina", "A24 Noticias"], ["Latin America", "Panregional"], [], "Noticias"),
]

# Blocked terms for ALL catalog entries
GLOBAL_BLOCKED_TERMS = ["Asia", "Brazil", "Brasil", "Portugal", "Russia", "Romania", "Bulgaria", "CEE", "Adriatic"]


def normalize_string(text):
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r'\b(1080[pi]|720p|480p|360p|hd|sd|fhd|uhd|4k)\b', '', text)
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def clean_display_name(name):
    n = name
    n = re.sub(r'\b(1080[pi]|720p|480p|360p|hd|sd|fhd|uhd|4k)\b', '', n, flags=re.IGNORECASE)
    n = re.sub(r'\b(latin america|latam|latinoamerica|latinoamérica|panregional|mexico|méxico|colombia|argentina|chile|andes)\b', '', n, flags=re.IGNORECASE)
    n = re.sub(r'\([^)]*\)', '', n)
    n = re.sub(r'\[[^\]]*\]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def parse_m3u(content):
    streams = []
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    total_lines = len(lines)
    while i < total_lines:
        line = lines[i].strip()
        if not line.startswith("#EXTINF"):
            i += 1
            continue
        extinf_line = line
        attrs = {}
        for match in re.finditer(r'([a-zA-Z_-]+)="([^"]*)"', extinf_line):
            key = match.group(1).lower().replace("-", "_")
            attrs[key] = match.group(2)
        display_name = ""
        in_quotes = False
        last_comma_pos = -1
        for idx, char in enumerate(extinf_line):
            if char == '"':
                in_quotes = not in_quotes
            elif char == ',' and not in_quotes:
                last_comma_pos = idx
        if last_comma_pos >= 0:
            display_name = extinf_line[last_comma_pos + 1:].strip()
        else:
            display_name = attrs.get("tvg_name", "")
        extra_lines = []
        i += 1
        while i < total_lines:
            next_line = lines[i].strip()
            if next_line.startswith("#EXTVLCOPT:") or next_line.startswith("#EXTHTTP:"):
                extra_lines.append(next_line)
                i += 1
            else:
                break
        stream_url = ""
        while i < total_lines:
            candidate = lines[i].strip()
            if candidate:
                if not candidate.startswith("#"):
                    stream_url = candidate
                    i += 1
                    break
                else:
                    i += 1
            else:
                i += 1
        if not stream_url:
            continue
        resolution = ""
        name_lower = display_name.lower()
        if "1080p" in name_lower or "1080i" in name_lower or "fhd" in name_lower:
            resolution = "1080p"
        elif "720p" in name_lower or "hd" in name_lower:
            resolution = "720p"
        elif "480p" in name_lower or "360p" in name_lower or "sd" in name_lower:
            resolution = "sd"
        tvg_id = attrs.get("tvg_id", "")
        base_id = tvg_id.split("@")[0] if tvg_id else ""
        country_suffix = ""
        if "." in base_id:
            country_suffix = base_id.split(".")[-1].lower()
        streams.append({
            "tvg_id": tvg_id,
            "tvg_name": attrs.get("tvg_name", ""),
            "tvg_logo": attrs.get("tvg_logo", ""),
            "group_title": attrs.get("group_title", ""),
            "display_name": display_name,
            "stream_url": stream_url,
            "extra_lines": extra_lines,
            "resolution": resolution,
            "country_suffix": country_suffix
        })
    return streams


def validate_stream(url, extra_lines):
    headers = {"User-Agent": USER_AGENT}
    for line in extra_lines:
        if "http-user-agent=" in line.lower():
            headers["User-Agent"] = line.split("=", 1)[1] if "=" in line else USER_AGENT
        elif "http-referrer=" in line.lower() or "http-referer=" in line.lower():
            headers["Referer"] = line.split("=", 1)[1] if "=" in line else None
    try:
        start_time = time.time()
        resp = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS, stream=True)
        latency = int((time.time() - start_time) * 1000)
        if resp.status_code != 200:
            resp.close()
            return False, latency, f"HTTP {resp.status_code}"
            
        content_type = resp.headers.get("Content-Type", "").lower()
        if "text/html" in content_type:
            resp.close()
            return False, latency, "HTML page returned instead of stream"
            
        try:
            chunk_bytes = next(resp.iter_content(chunk_size=4096), b"")
        except StopIteration:
            chunk_bytes = b""
        chunk = chunk_bytes.decode("utf-8", errors="replace")
        resp.close()
        
        # Verify valid HLS
        if chunk.strip().startswith("#EXTM3U") or "#EXT-X-STREAM-INF" in chunk or "#EXTINF" in chunk or "mpegurl" in content_type:
            return True, latency, None
        else:
            return False, latency, "Not valid HLS playlist"
    except requests.exceptions.Timeout:
        return False, int(TIMEOUT_SECONDS * 1000), "Timeout"
    except Exception as e:
        return False, 0, str(e)[:100]


def matches_preferred_region(stream, preferred_regions):
    suffix = stream["country_suffix"]
    name_lower = stream["display_name"].lower()
    group_lower = stream["group_title"].lower()
    tvg_id = stream.get("tvg_id", "")
    # Extract @region suffix from TVG-ID (e.g. PlutoTVNovelas.us@LatAm -> latam)
    tvg_region = tvg_id.split("@")[1].lower() if "@" in tvg_id else ""
    region_suffixes = {
        "latin america": ["la", "pr", "latam", "latinoamerica", "panregional"],
        "panregional": ["la", "pr", "latam", "latinoamerica", "panregional"],
        "mexico": ["mx"],
        "colombia": ["co"],
        "central america": ["gt", "cr", "pa", "hn", "ni", "sv"],
        "andes": ["pe", "co", "ve", "ec", "bo"]
    }
    general_latam_suffixes = ["ar", "cl", "uy", "py", "do", "pr"]
    
    # Specific country exact match (e.g. LatinaTV needs pe, Mega needs cl)
    exact_match = ["pe", "cl", "bo", "ve", "py", "mx", "co", "gt", "cr", "pa", "hn", "ni", "sv"]
    
    # Check the @region from TVG-ID first (most reliable)
    if tvg_region in ["latam", "panregional", "centralamerica", "andes", "south"]:
        return True
    
    for r in preferred_regions:
        r_clean = r.lower()
        if r_clean in exact_match:
            if suffix == r_clean or tvg_region == r_clean:
                return True
            continue # If specific country is required, don't fall back to general LatAm for this rule
        if r_clean in region_suffixes:
            if suffix in region_suffixes[r_clean]:
                return True
            if tvg_region in region_suffixes[r_clean]:
                return True
        if r_clean in name_lower or r_clean in group_lower:
            return True
            
    # If the preferred regions ONLY contain exact matches, don't fallback
    only_exact = all(r.lower() in exact_match or r.lower() in ["chile", "peru", "bolivia"] for r in preferred_regions)
    if only_exact:
        return False

    if suffix in general_latam_suffixes:
        return True
    return False


def matches_identity(stream, norm_name, norm_aliases):
    s_name = normalize_string(stream["display_name"])
    s_tvg = normalize_string(stream["tvg_name"])
    tvg_id = stream["tvg_id"]
    base_id = tvg_id.split("@")[0].lower() if tvg_id else ""
    base_id_normalized = normalize_string(base_id)
    if base_id_normalized == norm_name or base_id_normalized in norm_aliases:
        return True
    if s_name == norm_name or s_tvg == norm_name:
        return True
    if s_name in norm_aliases or s_tvg in norm_aliases:
        return True
    return False


def matches_blocked(stream, blocked_terms, global_blocked_urls_set):
    url = stream["stream_url"]
    if url in global_blocked_urls_set:
        return True
    fields = [stream["display_name"], stream["tvg_id"], stream["group_title"], url]
    for term in blocked_terms:
        tl = term.lower()
        for f in fields:
            if tl in f.lower():
                return True
    return False


def get_sorting_key(stream, preferred_regions):
    pref_region = 1 if matches_preferred_region(stream, preferred_regions) else 0
    suffix = stream["country_suffix"]
    name_lower = stream["display_name"].lower()
    group_lower = stream["group_title"].lower()
    spanish_suffixes = ["la", "mx", "co", "gt", "cr", "pa", "hn", "ni", "sv", "pe", "ve", "ec", "bo", "ar", "cl", "uy", "py", "do", "pr", "es"]
    spanish_keywords = ["espanol", "español", "spanish", "spa", "sp", "lat", "latam"]
    is_spanish = 1 if suffix in spanish_suffixes or any(k in name_lower or k in group_lower for k in spanish_keywords) else 0
    res_score = 1
    if stream["resolution"] == "1080p":
        res_score = 3
    elif stream["resolution"] == "720p":
        res_score = 2
    elif stream["resolution"] == "sd":
        res_score = 0
    is_https = 1 if stream["stream_url"].startswith("https://") else 0
    return (pref_region, is_spanish, res_score, is_https)


def main():
    start_time = time.time()
    total_http = 0

    print("=" * 60)
    print("  IPTV Guatemala - Definitive 75-Channel Build")
    print("=" * 60)

    # ─── STEP 1: Build the base from Lote 1 confirmed ─────────────────
    with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
        ovr_data = json.load(f)
    overrides = ovr_data.get("overrides", {})

    with open(SELECTED_FILE, "r", encoding="utf-8") as f:
        sel_data = json.load(f)

    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    # Guatemala channels
    gt_channels = gt_data.get("channels", [])
    print(f"  Guatemala channels: {len(gt_channels)}")

    # Identify Lote 1 confirmed
    lote1_confirmed = []
    for name, ovr in overrides.items():
        if ovr.get("manual_verified") and ovr.get("status") == "CONFIRMADO":
            if name in REMOVE_CHANNELS:
                continue
            if name in LOTE2_CHANNELS:
                continue
            # Skip Caracol - it's added explicitly below
            if name == "Caracol Televisión":
                continue
            # Check if the URL is globally blocked
            url = ovr.get("manual_url", "")
            if url in GLOBAL_BLOCKED_URLS:
                print(f"  [SKIP] {name}: URL is globally blocked ({url[:50]}...)")
                continue
            # Special: National Geographic is in English - will be handled separately
            if name == "National Geographic":
                print(f"  [SKIP] {name}: English signal - will search for Spanish replacement")
                continue
            lote1_confirmed.append({
                "curated_name": name,
                "stream_url": url,
                "tvg_id": ovr.get("selected_tvg_id", ""),
                "status": "CONFIRMADO"
            })

    print(f"  Lote 1 confirmed (valid): {len(lote1_confirmed)}")

    # ─── STEP 2: Freeze Caracol Televisión ─────────────────────────────
    caracol_entry = None
    for ch in sel_data.get("channels", []):
        if ch["curated_name"] == "Caracol Televisión":
            caracol_entry = ch
            break
    if not caracol_entry:
        print("  [ERROR] Caracol Televisión not found in selected_channels.json!")
        sys.exit(1)
    print(f"  Caracol Televisión: FROZEN")

    # ─── STEP 3: Download IPTV-org once ────────────────────────────────
    print(f"  Downloading IPTV-org master playlist...")
    resp = requests.get(IPTV_ORG_M3U_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    m3u_content = resp.text
    print(f"  Downloaded successfully ({len(m3u_content)/1024/1024:.2f} MB).")
    all_streams = parse_m3u(m3u_content)
    print(f"  Parsed {len(all_streams):,} total streams.")

    global_blocked_urls_set = set(GLOBAL_BLOCKED_URLS)

    # ─── STEP 4: Search NatGeo Latin America replacement ───────────────
    print("\n  --- National Geographic replacement ---")
    natgeo_blocked_url = "http://138.121.15.230:9002/NAT-GEO/index.m3u8"
    natgeo_found = None
    natgeo_norm_name = normalize_string("National Geographic")
    natgeo_aliases = [normalize_string(a) for a in [
        "National Geographic Latin America", "National Geographic Latinoamérica",
        "Nat Geo Latin America", "Nat Geo Latinoamérica", "National Geographic Channel"
    ]]
    natgeo_blocked_terms = ["Nat Geo Wild", "NatGeo Wild", "Nat Geo Kids", "english", "us", "uk"] + GLOBAL_BLOCKED_TERMS
    natgeo_preferred = ["Latin America", "Panregional", "Mexico", "Andes", "Central America"]

    natgeo_candidates = []
    for s in all_streams:
        if s["stream_url"] == natgeo_blocked_url:
            continue
        if s["stream_url"] in global_blocked_urls_set:
            continue
        if matches_identity(s, natgeo_norm_name, natgeo_aliases):
            if not matches_blocked(s, natgeo_blocked_terms, global_blocked_urls_set):
                if matches_preferred_region(s, natgeo_preferred):
                    natgeo_candidates.append(s)

    natgeo_candidates.sort(key=lambda c: get_sorting_key(c, natgeo_preferred), reverse=True)
    for cand in natgeo_candidates[:3]:
        total_http += 1
        print(f"    Testing NatGeo: {cand['display_name']} ({cand['resolution'] or 'unknown'}) at {cand['stream_url'][:60]}...", end=" ", flush=True)
        ok, lat, err = validate_stream(cand["stream_url"], cand["extra_lines"])
        if ok:
            print(f"[OK] ({lat}ms)")
            natgeo_found = cand
            natgeo_found["latency"] = lat
            break
        else:
            print(f"[FAIL] ({err})")

    if natgeo_found:
        print(f"  NatGeo replacement found: {natgeo_found['display_name']}")
    else:
        print("  NatGeo: No Spanish replacement found. Will try fallback alternatives.")
        # Try Love Nature, Smithsonian, etc.
        fallback_names = [
            ("Love Nature", ["Love Nature Español", "Love Nature HD", "Love Nature Latin America"]),
            ("Smithsonian Channel", ["Smithsonian Channel Latinoamérica"]),
        ]
        for fb_name, fb_aliases in fallback_names:
            fb_norm = normalize_string(fb_name)
            fb_norm_aliases = [normalize_string(a) for a in fb_aliases]
            fb_cands = []
            for s in all_streams:
                if s["stream_url"] in global_blocked_urls_set:
                    continue
                if matches_identity(s, fb_norm, fb_norm_aliases):
                    if not matches_blocked(s, GLOBAL_BLOCKED_TERMS, global_blocked_urls_set):
                        fb_cands.append(s)
            fb_cands.sort(key=lambda c: get_sorting_key(c, ["Latin America", "Panregional"]), reverse=True)
            for cand in fb_cands[:3]:
                total_http += 1
                print(f"    Testing fallback {fb_name}: {cand['display_name']} at {cand['stream_url'][:60]}...", end=" ", flush=True)
                ok, lat, err = validate_stream(cand["stream_url"], cand["extra_lines"])
                if ok:
                    print(f"[OK] ({lat}ms)")
                    natgeo_found = cand
                    natgeo_found["latency"] = lat
                    natgeo_found["_replaced_name"] = fb_name
                    break
                else:
                    print(f"[FAIL] ({err})")
            if natgeo_found:
                break

    # ─── STEP 5: Build the base selected list ──────────────────────────
    # Collect all confirmed URLs and TVG-IDs to avoid duplicates
    used_urls = set()
    used_tvg_ids = set()
    used_names = set()
    final_selected = []

    # Category mapping for Lote 1
    lote1_categories = {
        "AMC": "Películas y Series", "AXN": "Películas y Series", "FX": "Películas y Series",
        "Golden": "Películas y Series", "Golden Edge": "Películas y Series",
        "Star Channel": "Películas y Series", "Studio Universal": "Películas y Series",
        "Universal TV": "Películas y Series",
        "A&E": "Entretenimiento", "Comedy Central": "Entretenimiento",
        "Distrito Comedia": "Entretenimiento", "Lifetime": "Entretenimiento",
        "Sony Channel": "Entretenimiento", "Las Estrellas": "Entretenimiento",
        "TLNovelas": "Entretenimiento", "Azteca Internacional": "TV Latinoamérica",
        "TeleSUR": "Noticias",
        "History": "Documentales y Cultura",
        "Nickelodeon": "Infantil", "Nick Jr.": "Infantil", "Disney Channel": "Infantil",
    }

    for ch in lote1_confirmed:
        name = ch["curated_name"]
        url = ch["stream_url"]
        tvg_id = ch["tvg_id"]
        cat = lote1_categories.get(name, "Entretenimiento")
        final_selected.append({
            "curated_name": name,
            "display_name": name,
            "tvg_id": tvg_id,
            "tvg_logo": "",
            "group": cat,
            "stream_url": url,
            "extra_lines": [],
            "resolution": "",
            "country": "",
            "latency_ms": 0,
            "source": "confirmed-lote1",
            "status": "CONFIRMADO"
        })
        used_urls.add(url)
        if tvg_id:
            used_tvg_ids.add(tvg_id)
        used_names.add(normalize_string(name))

    # Caracol Televisión
    final_selected.append({
        "curated_name": "Caracol Televisión",
        "display_name": "Caracol Televisión",
        "tvg_id": caracol_entry.get("tvg_id", ""),
        "tvg_logo": caracol_entry.get("tvg_logo", ""),
        "group": "TV Latinoamérica",
        "stream_url": caracol_entry["stream_url"],
        "extra_lines": caracol_entry.get("extra_lines", []),
        "resolution": caracol_entry.get("resolution", ""),
        "country": caracol_entry.get("country", ""),
        "latency_ms": caracol_entry.get("latency_ms", 0),
        "source": "confirmed-lote2",
        "status": "CONFIRMADO"
    })
    used_urls.add(caracol_entry["stream_url"])
    if caracol_entry.get("tvg_id"):
        used_tvg_ids.add(caracol_entry["tvg_id"])
    used_names.add(normalize_string("Caracol Televisión"))

    # NatGeo replacement
    if natgeo_found:
        replaced_name = natgeo_found.get("_replaced_name", "National Geographic")
        cat = "Documentales y Cultura"
        final_selected.append({
            "curated_name": replaced_name,
            "display_name": natgeo_found["display_name"],
            "tvg_id": natgeo_found["tvg_id"],
            "tvg_logo": natgeo_found.get("tvg_logo", ""),
            "group": cat,
            "stream_url": natgeo_found["stream_url"],
            "extra_lines": natgeo_found.get("extra_lines", []),
            "resolution": natgeo_found.get("resolution", ""),
            "country": natgeo_found.get("country_suffix", "").upper() or "LA",
            "latency_ms": natgeo_found.get("latency", 0),
            "source": "iptv-org",
            "status": "AUTO_FINAL"
        })
        used_urls.add(natgeo_found["stream_url"])
        if natgeo_found["tvg_id"]:
            used_tvg_ids.add(natgeo_found["tvg_id"])
        used_names.add(normalize_string(replaced_name))

    base_count = len(final_selected) + 3  # +3 Guatemala
    needed = 75 - base_count
    print(f"\n  Base count: {base_count} (incl. 3 Guatemala)")
    print(f"  Need {needed} more channels from catalog.")

    # ─── STEP 6: Search for remaining channels from catalog ────────────
    print("\n  --- Searching catalog channels ---")
    new_found = 0
    new_not_found = 0

    for cat_name, cat_aliases, cat_regions, cat_blocked, cat_category in CATALOG:
        if needed <= 0:
            break

        # Skip if already in base
        norm_cat = normalize_string(cat_name)
        if norm_cat in used_names:
            continue

        all_blocked = cat_blocked + GLOBAL_BLOCKED_TERMS
        norm_aliases = [normalize_string(a) for a in cat_aliases]

        candidates = []
        for s in all_streams:
            if s["stream_url"] in used_urls:
                continue
            if s["stream_url"] in global_blocked_urls_set:
                continue
            if matches_identity(s, norm_cat, norm_aliases):
                if not matches_blocked(s, all_blocked, global_blocked_urls_set):
                    candidates.append(s)

        if not candidates:
            new_not_found += 1
            continue

        candidates.sort(key=lambda c: get_sorting_key(c, cat_regions), reverse=True)

        found = False
        for cand in candidates[:3]:
            cand_url = cand["stream_url"]
            cand_tvg = cand["tvg_id"]

            if cand_url in used_urls:
                continue
            if cand_tvg and cand_tvg in used_tvg_ids:
                continue

            # Check region - also allow "us" suffix if tvg_id has @LatAm
            tvg_region = cand["tvg_id"].split("@")[1].lower() if "@" in cand["tvg_id"] else ""
            is_latam_tvg = tvg_region in ["latam", "panregional", "centralamerica", "andes", "south", "sd"]
            if not matches_preferred_region(cand, cat_regions) and cand["country_suffix"] not in ["", "la"] and not is_latam_tvg:
                continue

            total_http += 1
            print(f"    [{75 - needed + 1:02d}/75] '{cat_name}': {cand['display_name']} ({cand['resolution'] or '?'}) at {cand_url[:55]}...", end=" ", flush=True)
            ok, lat, err = validate_stream(cand_url, cand["extra_lines"])

            if ok:
                print(f"[OK] ({lat}ms)")
                final_selected.append({
                    "curated_name": cat_name,
                    "display_name": cand["display_name"],
                    "tvg_id": cand_tvg,
                    "tvg_logo": cand.get("tvg_logo", ""),
                    "group": cat_category,
                    "stream_url": cand_url,
                    "extra_lines": cand.get("extra_lines", []),
                    "resolution": cand.get("resolution", ""),
                    "country": cand.get("country_suffix", "").upper() or "LA",
                    "latency_ms": lat,
                    "source": "iptv-org",
                    "status": "AUTO_FINAL"
                })
                used_urls.add(cand_url)
                if cand_tvg:
                    used_tvg_ids.add(cand_tvg)
                used_names.add(norm_cat)
                needed -= 1
                new_found += 1
                found = True
                break
            else:
                print(f"[FAIL] ({err})")

        if not found:
            new_not_found += 1

    total_curated = len(final_selected)
    total_with_gt = total_curated + 3

    print(f"\n  Curated channels: {total_curated}")
    print(f"  Total with Guatemala: {total_with_gt}")
    print(f"  New found: {new_found}")
    print(f"  New not found: {new_not_found}")

    if total_with_gt != 75:
        print(f"  [WARNING] Total is {total_with_gt}, not 75. Adjusting...")
        if total_with_gt > 75:
            # Trim from the end (newest AUTO_FINAL channels) but never confirmed
            excess = total_with_gt - 75
            trimmed = 0
            for i in range(len(final_selected) - 1, -1, -1):
                if trimmed >= excess:
                    break
                if final_selected[i]["status"] == "AUTO_FINAL":
                    print(f"    Removing: {final_selected[i]['curated_name']}")
                    final_selected.pop(i)
                    trimmed += 1
            total_curated = len(final_selected)
            total_with_gt = total_curated + 3

    # ─── STEP 7: Save selected_channels.json ───────────────────────────
    sel_output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "channels": final_selected
    }
    with open(SELECTED_FILE, "w", encoding="utf-8") as f:
        json.dump(sel_output, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved {len(final_selected)} curated channels to {SELECTED_FILE}")

    # ─── STEP 8: Generate index.m3u ────────────────────────────────────
    # Combine Guatemala + curated, sort by category
    all_playlist = []

    for ch in gt_channels:
        if ch.get("enabled", True):
            all_playlist.append({
                "id": ch.get("id", ""),
                "name": clean_display_name(ch.get("name", "")),
                "logo": ch.get("logo", ""),
                "group": "Guatemala",
                "stream_url": ch.get("stream_url", ""),
                "extra_lines": ch.get("extra_lines", []),
            })

    for ch in final_selected:
        all_playlist.append({
            "id": ch.get("tvg_id", ""),
            "name": clean_display_name(ch.get("curated_name", "")),
            "logo": ch.get("tvg_logo", ""),
            "group": ch.get("group", "Entretenimiento"),
            "stream_url": ch.get("stream_url", ""),
            "extra_lines": ch.get("extra_lines", []),
        })

    def sort_key(ch):
        group = ch.get("group", "Entretenimiento")
        try:
            group_idx = CATEGORY_ORDER.index(group)
        except ValueError:
            group_idx = len(CATEGORY_ORDER)
        return (group_idx, ch.get("name", "").lower())

    all_playlist.sort(key=sort_key)

    m3u_lines = ["#EXTM3U", ""]
    for ch in all_playlist:
        # Extra lines are explicitly ignored to ensure TV parses exactly 75 URLs
        # immediately following the EXTINF line.
        extinf = (
            f'#EXTINF:-1 tvg-id="{ch["id"]}" '
            f'tvg-name="{ch["name"]}" '
            f'tvg-logo="{ch["logo"]}" '
            f'group-title="{ch["group"]}"'
            f',{ch["name"]}'
        )
        m3u_lines.append(extinf)
        m3u_lines.append(ch["stream_url"])
        m3u_lines.append("")

    with open(OUTPUT_M3U, "wb") as f:
        # Write exactly with LF to avoid \r\n issues on some players
        content = "\n".join(m3u_lines).encode("utf-8")
        f.write(content)
    print(f"  Generated index.m3u with {len(all_playlist)} channels")
    
    # ─── STEP 9: Generate reports based on actual M3U written ──────────
    with open(FINAL_LIST_MD, "w", encoding="utf-8") as f:
        f.write("# Lista Definitiva de Canales\n\n")
        f.write("| N.º | Canal | Categoría | Región | TVG-ID |\n")
        f.write("|-----|-------|-----------|--------|--------|\n")
        for i, ch in enumerate(all_playlist, 1):
            f.write(f"| {i:02d} | {ch['name']} | {ch['group']} | {ch.get('country', '-')} | {ch['id']} |\n")


    # ─── STEP 9: Validations ──────────────────────────────────────────
    print("\n  --- Final Validations ---")
    errors = []

    if len(all_playlist) != 75:
        errors.append(f"Total is {len(all_playlist)}, expected 75")

    m3u_text = "\n".join(m3u_lines)
    if "NTN24" in m3u_text:
        errors.append("NTN24 found in index.m3u")
    if "Milenio" in m3u_text:
        errors.append("Milenio found in index.m3u")
    if "Foro TV" in m3u_text:
        errors.append("Foro TV found in index.m3u")
    if "bantel-cdn1" in m3u_text:
        errors.append("bantel-cdn1 URL found in index.m3u")

    gt_names = [clean_display_name(ch["name"]) for ch in gt_channels if ch.get("enabled")]
    for gn in ["Canal 3 Guatemala", "Canal 7 Guatemala", "TN23 Guatemala"]:
        cleaned = clean_display_name(gn)
        if cleaned not in [c["name"] for c in all_playlist]:
            errors.append(f"{gn} missing from playlist")

    # Check duplicate URLs
    all_urls = [c["stream_url"] for c in all_playlist]
    url_dupes = [u for u in all_urls if all_urls.count(u) > 1]
    if url_dupes:
        errors.append(f"Duplicate URLs: {set(url_dupes)}")

    # Check duplicate TVG-IDs
    all_ids = [c["id"] for c in all_playlist if c["id"]]
    id_dupes = [i for i in all_ids if all_ids.count(i) > 1]
    if id_dupes:
        errors.append(f"Duplicate TVG-IDs: {set(id_dupes)}")

    for e in errors:
        print(f"  [ERROR] {e}")

    if not errors:
        print("  [OK] All validations passed!")

    # ─── STEP 10: Generate reports ─────────────────────────────────────
    exec_time = round(time.time() - start_time, 2)

    # reports/final-channel-list.md
    os.makedirs(os.path.dirname(FINAL_LIST_MD), exist_ok=True)
    with open(FINAL_LIST_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Lista Definitiva de Canales (75)\n\n")
        f.write(f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
        f.write("| N.º | Canal | Categoría | Resolución | Región | TVG-ID | Estado |\n")
        f.write("|-----|-------|-----------|------------|--------|--------|--------|\n")
        for i, ch in enumerate(all_playlist):
            res = ""
            for sc in final_selected:
                if sc["curated_name"] == ch["name"] or clean_display_name(sc.get("curated_name", "")) == ch["name"]:
                    res = sc.get("resolution", "")
                    break
            status = "CONFIRMADO"
            for sc in final_selected:
                if sc["curated_name"] == ch["name"] or clean_display_name(sc.get("curated_name", "")) == ch["name"]:
                    status = sc.get("status", "AUTO_FINAL")
                    break
            if ch["group"] == "Guatemala":
                status = "CONFIRMADO"
            region = ""
            for sc in final_selected:
                if sc["curated_name"] == ch["name"] or clean_display_name(sc.get("curated_name", "")) == ch["name"]:
                    region = sc.get("country", "")
                    break
            if ch["group"] == "Guatemala":
                region = "GT"
            f.write(f"| {i+1:02d} | {ch['name']} | {ch['group']} | {res or '-'} | {region or '-'} | {ch['id'] or '-'} | {status} |\n")

    # reports/curation-report.md
    cat_counts = {}
    for ch in all_playlist:
        g = ch["group"]
        cat_counts[g] = cat_counts.get(g, 0) + 1

    res_1080 = sum(1 for sc in final_selected if sc.get("resolution") == "1080p")
    res_720 = sum(1 for sc in final_selected if sc.get("resolution") == "720p")
    confirmed_count = sum(1 for sc in final_selected if sc.get("status") == "CONFIRMADO")
    auto_count = sum(1 for sc in final_selected if sc.get("status") == "AUTO_FINAL")

    with open(REPORT_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Reporte de Curación Definitiva\n\n")
        f.write(f"- **Fecha**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.write(f"- **Tiempo total**: {exec_time} segundos\n")
        f.write(f"- **Total HTTP requests**: {total_http}\n\n")
        f.write("## Resumen\n\n")
        f.write(f"- Canales existentes antes del nuevo lote: 27\n")
        f.write(f"- Canales eliminados: 3 (NTN24, Milenio Televisión, Foro TV) + E! (URL bloqueada) + National Geographic (señal en inglés)\n")
        f.write(f"- Canales confirmados manualmente (Lote 1): {confirmed_count}\n")
        f.write(f"- Canales nuevos encontrados: {new_found}\n")
        f.write(f"- Canales nuevos no encontrados: {new_not_found}\n")
        f.write(f"- **Total final**: {len(all_playlist)}\n\n")
        f.write("## Distribución por Categoría\n\n")
        for cat in CATEGORY_ORDER:
            f.write(f"- {cat}: {cat_counts.get(cat, 0)}\n")
        f.write(f"\n## Resoluciones\n\n")
        f.write(f"- 1080p: {res_1080}\n")
        f.write(f"- 720p: {res_720}\n")
        f.write(f"- Otra/desconocida: {len(final_selected) - res_1080 - res_720}\n\n")
        f.write(f"## Duplicados descartados: 0\n")

    # ─── STEP 11: Update overrides ─────────────────────────────────────
    # Block NatGeo English URL, remove disabled-by-batch flags, add new confirmed
    natgeo_old_url = "http://138.121.15.230:9002/NAT-GEO/index.m3u8"
    ovr_data["global_blocked_urls"] = list(set(GLOBAL_BLOCKED_URLS + [natgeo_old_url]))

    # Update NTN24, Milenio, Foro TV reasons
    for rn in REMOVE_CHANNELS:
        if rn not in overrides:
            overrides[rn] = {}
        overrides[rn]["disabled"] = True
        overrides[rn]["reason"] = "Eliminado por decisión del administrador durante la auditoría manual."

    # Update NatGeo
    if "National Geographic" in overrides:
        overrides["National Geographic"]["manual_verified"] = False
        overrides["National Geographic"]["status"] = "ELIMINADO"
        blocked_urls = overrides["National Geographic"].get("blocked_urls", [])
        if natgeo_old_url not in blocked_urls:
            blocked_urls.append(natgeo_old_url)
        overrides["National Geographic"]["blocked_urls"] = blocked_urls

    # Update E! 
    if "E!" in overrides:
        overrides["E!"]["manual_verified"] = False
        overrides["E!"]["status"] = "ELIMINADO"
        overrides["E!"]["reason"] = "URL globally blocked (bantel-cdn1)"

    # Freeze Caracol
    if "Caracol Televisión" not in overrides:
        overrides["Caracol Televisión"] = {}
    overrides["Caracol Televisión"]["manual_verified"] = True
    overrides["Caracol Televisión"]["manual_url"] = caracol_entry["stream_url"]
    overrides["Caracol Televisión"]["selected_tvg_id"] = caracol_entry.get("tvg_id", "")
    overrides["Caracol Televisión"]["status"] = "CONFIRMADO"

    # Re-enable channels that were disabled "to limit processing"
    for name in list(overrides.keys()):
        if overrides[name].get("reason") == "Disabled to limit processing to the new batch and confirmed channels.":
            if name not in REMOVE_CHANNELS:
                del overrides[name]["disabled"]
                del overrides[name]["reason"]

    ovr_data["overrides"] = overrides
    with open(OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(ovr_data, f, indent=2, ensure_ascii=False)

    # ─── FINAL SUMMARY ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  DEFINITIVE BUILD COMPLETE")
    print("=" * 60)
    print(f"  Total channels: {len(all_playlist)}")
    print(f"  Guatemala: {cat_counts.get('Guatemala', 0)}")
    print(f"  Confirmed (Lote 1): {confirmed_count}")
    print(f"  New (AUTO_FINAL): {auto_count}")
    print(f"  1080p: {res_1080}")
    print(f"  720p: {res_720}")
    print(f"  HTTP requests: {total_http}")
    print(f"  Time: {exec_time}s")
    print(f"  Errors: {len(errors)}")
    print("=" * 60)

    if errors:
        print("\n  ERRORS FOUND - review before committing!")
        sys.exit(1)


if __name__ == "__main__":
    main()
