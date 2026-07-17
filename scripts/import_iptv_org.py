#!/usr/bin/env python3
"""
import_iptv_org.py — Motor de descubrimiento y clasificación automática de canales latinoamericanos de IPTV-org.

Descarga y procesa:
- https://iptv-org.github.io/iptv/index.m3u
- API de IPTV-org (channels.json, feeds.json, countries.json)

Aplica un motor de puntuación para descubrir automáticamente canales en español latino
y los filtra, valida de forma concurrente, deduplica por canal base, y genera reportes.
"""

import concurrent.futures
import io
import json
import os
import re
import sys
import threading
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

# Force UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ─── Paths ───────────────────────────────────────────────────────────
BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_FILE = os.path.join(BASE_DIR, "data", "discovery_config.json")
WANTED_FILE = os.path.join(BASE_DIR, "data", "wanted_channels.json")
OVERRIDES_FILE = os.path.join(BASE_DIR, "data", "channel_overrides.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "imported_channels.json")
CANDIDATES_FILE = os.path.join(BASE_DIR, "data", "discovered_candidates.json")

REPORT_JSON = os.path.join(BASE_DIR, "reports", "discovery-report.json")
REPORT_MD = os.path.join(BASE_DIR, "reports", "discovery-report.md")
DUPLICATES_REPORT_MD = os.path.join(BASE_DIR, "reports", "duplicates-report.md")

IPTV_ORG_URL = "https://iptv-org.github.io/iptv/index.m3u"

# ─── HTTP Config ─────────────────────────────────────────────────────
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT_SECONDS = 8
MAX_RETRIES = 2
RETRY_DELAY = 1


# ═══════════════════════════════════════════════════════════════════════
# M3U PARSER
# ═══════════════════════════════════════════════════════════════════════

def parse_m3u(content):
    """Parse extended M3U content into a list of stream dicts."""
    channels = []
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    
    i = 0
    total_lines = len(lines)
    
    while i < total_lines:
        line = lines[i].strip()
        
        if not line.startswith("#EXTINF"):
            i += 1
            continue
        
        extinf_line = line
        
        # Extract attributes
        attrs = {}
        for match in re.finditer(r'([a-zA-Z_-]+)="([^"]*)"', extinf_line):
            key = match.group(1).lower().replace("-", "_")
            attrs[key] = match.group(2)
        
        # Extract display name
        display_name = _extract_display_name(extinf_line)
        
        # Collect extra lines (#EXTVLCOPT, #EXTHTTP)
        extra_lines = []
        i += 1
        while i < total_lines:
            next_line = lines[i].strip()
            if next_line.startswith("#EXTVLCOPT:") or next_line.startswith("#EXTHTTP:"):
                extra_lines.append(next_line)
                i += 1
            else:
                break
        
        # Get stream URL
        stream_url = ""
        if i < total_lines:
            candidate = lines[i].strip()
            if candidate and not candidate.startswith("#"):
                stream_url = candidate
                i += 1
        
        if not stream_url:
            continue
        
        # Extract user-agent and referrer
        user_agent = None
        referrer = None
        for el in extra_lines:
            if "http-user-agent=" in el.lower():
                user_agent = el.split("=", 1)[1] if "=" in el else None
            elif "http-referrer=" in el.lower() or "http-referer=" in el.lower():
                referrer = el.split("=", 1)[1] if "=" in el else None
        
        resolution = _detect_resolution(display_name)
        
        channel = {
            "tvg_id": attrs.get("tvg_id", ""),
            "tvg_name": attrs.get("tvg_name", ""),
            "tvg_logo": attrs.get("tvg_logo", ""),
            "group_title": attrs.get("group_title", ""),
            "display_name": display_name,
            "stream_url": stream_url,
            "user_agent": user_agent,
            "referrer": referrer,
            "extra_lines": extra_lines,
            "resolution": resolution,
        }
        channels.append(channel)
        
    return channels


def _extract_display_name(extinf_line):
    in_quotes = False
    last_comma_pos = -1
    for idx, ch in enumerate(extinf_line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ',' and not in_quotes:
            last_comma_pos = idx
            
    if last_comma_pos >= 0:
        return extinf_line[last_comma_pos + 1:].strip()
        
    match = re.search(r'tvg-name="([^"]*)"', extinf_line)
    if match:
        return match.group(1)
    return ""


def _detect_resolution(name):
    name_lower = name.lower()
    if "1080p" in name_lower or "1080i" in name_lower:
        return "1080p"
    elif "720p" in name_lower:
        return "720p"
    elif "480p" in name_lower:
        return "480p"
    elif "360p" in name_lower:
        return "360p"
    elif " hd" in name_lower or "(hd)" in name_lower:
        return "720p"
    elif " sd" in name_lower or "(sd)" in name_lower:
        return "480p"
    return ""


# ═══════════════════════════════════════════════════════════════════════
# METADATA DOWNLOAD & BASE NAME NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════

def download_m3u():
    print("  Descargando lista maestra M3U...")
    resp = requests.get(IPTV_ORG_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return resp.text


def download_api_metadata():
    print("  Descargando metadata de canales (IPTV-org API)...")
    channels_data = requests.get("https://iptv-org.github.io/api/channels.json", timeout=30).json()
    channels_map = {c["id"]: c for c in channels_data}
    
    print("  Descargando metadata de feeds (IPTV-org API)...")
    feeds_data = requests.get("https://iptv-org.github.io/api/feeds.json", timeout=30).json()
    feeds_map = {}
    for f in feeds_data:
        feeds_map[(f["channel"], f["id"])] = f
        
    print("  Descargando metadata de paises (IPTV-org API)...")
    countries_data = requests.get("https://iptv-org.github.io/api/countries.json", timeout=30).json()
    countries_map = {c["code"]: c for c in countries_data}
    
    return channels_map, feeds_map, countries_map


def normalize_name(name):
    s = name.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r'\b(1080[pi]|720p|480p|360p|hd|sd|fhd|uhd|4k)\b', '', s)
    s = re.sub(r'\([^)]*\)', '', s)
    s = re.sub(r'\[[^\]]*\]', '', s)
    s = re.sub(r'[-_]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def get_base_name(stream, channels_map):
    tvg_id = stream.get("tvg_id", "")
    if tvg_id:
        base_id = tvg_id.split("@")[0]
        if base_id in channels_map:
            return channels_map[base_id]["name"]
            
    # Clean display name fallback
    name = stream["display_name"]
    name = re.sub(r'\b(1080[pi]|720p|480p|360p|hd|sd|fhd|uhd|4k)\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    
    region_suffixes = [
        "latin america", "latam", "mexico", "colombia", "argentina", "chile", 
        "central america", "centroamerica", "venezuela", "ecuador", "peru", 
        "bolivia", "paraguay", "uruguay", "brazil", "brasil", "costa rica", 
        "panama", "el salvador", "honduras", "nicaragua"
    ]
    for suffix in region_suffixes:
        name = re.sub(r'\b' + re.escape(suffix) + r'\b', '', name, flags=re.IGNORECASE)
        
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def matches_blocked_terms(text, blocked_terms):
    text_lower = text.lower()
    for term in blocked_terms:
        if term.lower() in text_lower:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# SCORING & CLASSIFICATION ENGINE
# ═══════════════════════════════════════════════════════════════════════

def calculate_score(stream, base_name, channels_map, feeds_map, countries_map, overrides, config):
    score = 0
    reasons = []
    
    tvg_id = stream.get("tvg_id", "")
    base_id = tvg_id.split("@")[0] if tvg_id else None
    feed_id = tvg_id.split("@")[1] if tvg_id and "@" in tvg_id else None
    
    ch_meta = channels_map.get(base_id) if base_id else None
    feed_meta = feeds_map.get((base_id, feed_id)) if base_id and feed_id else None
    
    country_code = ch_meta.get("country") if ch_meta else None
    if not country_code and base_id and "." in base_id:
        ext = base_id.split(".")[-1]
        if len(ext) == 2:
            country_code = ext.upper()
            
    country_meta = countries_map.get(country_code) if country_code else None
    categories = [cat.lower() for cat in ch_meta.get("categories", [])] if ch_meta else []
    
    languages = []
    if feed_meta and feed_meta.get("languages"):
        languages = feed_meta["languages"]
    elif country_meta and country_meta.get("languages"):
        languages = country_meta["languages"]
        
    full_text_lower = f"{stream['display_name']} {stream['tvg_name']} {stream['tvg_id']}".lower()
    
    # ── Override and Block checks ──
    override = overrides.get(base_name, {})
    if override.get("block", False):
        score -= 2000
        reasons.append("bloqueado totalmente por override (-2000)")
        
    if override.get("blocked_terms"):
        if matches_blocked_terms(full_text_lower + " " + stream["stream_url"].lower(), override["blocked_terms"]):
            score -= 1000
            reasons.append("término bloqueado por override (-1000)")
            
    # Global excluded terms
    for term in config.get("excluded_terms", []):
        if term.lower() in full_text_lower:
            score -= 1000
            reasons.append(f"término excluido global '{term}' (-1000)")
            
    # Excluded categories
    for cat in categories:
        if cat in [ec.lower() for ec in config.get("excluded_categories", [])]:
            if cat == "religious" and config.get("include_religious", False):
                continue
            elif cat == "shop" and config.get("include_shopping", False):
                continue
            elif cat == "adult" and config.get("include_adult", False):
                continue
                
            if cat == "adult":
                score -= 1000
                reasons.append("categoría Adult (-1000)")
            elif cat == "shop":
                score -= 800
                reasons.append("categoría Shopping (-800)")
            elif cat == "religious":
                score -= 600
                reasons.append("categoría Religious (-600)")
                
    # Excluded country codes
    if country_code in config.get("excluded_country_codes", []):
        score -= 1000
        reasons.append(f"país excluido {country_code} (-1000)")
        
    # Closed channel check
    if ch_meta and ch_meta.get("closed"):
        score -= 1000
        reasons.append("canal marcado como cerrado en base de datos (-1000)")
        
    # ── Positives ──
    is_spanish = False
    spanish_langs = ["es", "spa", "spanish", "español", "espanol"]
    if any(lang in spanish_langs for lang in languages) or "espanol" in full_text_lower or "español" in full_text_lower:
        is_spanish = True
        score += 100
        reasons.append("idioma español confirmado (+100)")
        
    # Portuguese check
    portuguese_langs = ["pt", "por", "portuguese", "português"]
    if any(lang in portuguese_langs for lang in languages) or "portugues" in full_text_lower:
        score -= 1000
        reasons.append("idioma portugués (-1000)")
        
    # Latin America region
    has_latam_region = False
    latam_keywords = ["latin america", "latinoamerica", "latinoamérica", "latam", "panregional", "pan regional", "hispanic"]
    if any(kw in full_text_lower for kw in latam_keywords):
        has_latam_region = True
        score += 80
        reasons.append("región Latin America/LATAM (+80)")
        
    # Country-specific boosts
    if country_code == "MX" or "mexico" in full_text_lower or "méxico" in full_text_lower:
        score += 70
        reasons.append("región México (+70)")
    elif country_code == "CO" or "colombia" in full_text_lower:
        score += 65
        reasons.append("región Colombia (+65)")
    elif country_code in ["GT", "SV", "HN", "NI", "CR", "PA"] or "centroamerica" in full_text_lower or "centroamérica" in full_text_lower:
        score += 60
        reasons.append("región Centroamérica (+60)")
    elif country_code in ["PE", "EC", "VE", "CL", "AR", "UY", "PY", "BO", "DO", "PR"]:
        score += 50
        reasons.append(f"país hispanoamericano permitido ({country_code}) (+50)")
        if country_code in ["PE", "EC", "VE", "BO"] or "andes" in full_text_lower or "andino" in full_text_lower:
            score += 55
            reasons.append("región Andes (+55)")
            
    # International Spanish
    if country_code not in ["GT", "MX", "CO", "SV", "HN", "NI", "CR", "PA", "PE", "EC", "VE", "DO", "PR", "BO", "PY", "UY", "CL", "AR"] and is_spanish:
        score += 45
        reasons.append("canal internacional en español (+45)")
        
    # Categories
    permitted_categories = ["general", "movies", "series", "news", "documentary", "sports", "music", "kids", "education", "culture"]
    if any(cat in permitted_categories for cat in categories):
        score += 35
        reasons.append("categoría permitida (+35)")
        
    # Quality
    res = stream.get("resolution", "")
    if res == "1080p":
        score += 25
        reasons.append("calidad 1080p (+25)")
    elif res == "720p":
        score += 15
        reasons.append("calidad 720p (+15)")
        
    # URL / Metadata
    if stream.get("stream_url", "").startswith("https://"):
        score += 10
        reasons.append("usa HTTPS (+10)")
    if stream.get("tvg_logo"):
        score += 10
        reasons.append("tiene logo (+10)")
    if stream.get("tvg_id"):
        score += 10
        reasons.append("tiene tvg-id (+10)")
    if ch_meta and ch_meta.get("website") and ch_meta.get("network"):
        score += 10
        reasons.append("metadata completa (+10)")
    if feed_meta and len(feed_meta.get("broadcast_area", [])) > 1:
        score += 10
        reasons.append("canal panregional (+10)")
        
    # Exclude purely English feeds
    if languages == ["eng"] and not is_spanish:
        score -= 500
        reasons.append("feed exclusivamente en inglés (-500)")
        
    # Unknown region penalty
    if not country_code and not has_latam_region and not is_spanish:
        score -= 400
        reasons.append("región desconocida sin evidencia de español (-400)")
        
    return score, reasons


def classify_category(base_name, channels_map, override):
    # Check manual override category
    if override.get("category_final"):
        return override["category_final"]
        
    # Lookup canonical categories
    ch_meta = None
    for cid, meta in channels_map.items():
        if meta["name"].lower() == base_name.lower():
            ch_meta = meta
            break
            
    categories = [cat.lower() for cat in ch_meta.get("categories", [])] if ch_meta else []
    country = ch_meta.get("country", "") if ch_meta else ""
    
    if "news" in categories or "noticias" in categories:
        return "Noticias en español"
    elif any(c in categories for c in ["movies", "series", "cinema", "films"]):
        return "Películas y Series"
    elif "sports" in categories or "deportes" in categories:
        return "Deportes"
    elif any(c in categories for c in ["kids", "children", "animation", "infantil"]):
        return "Infantil"
    elif any(c in categories for c in ["documentary", "science", "history", "documentales"]):
        return "Documentales"
    elif any(c in categories for c in ["education", "culture", "cultura", "educación"]):
        return "Cultura y Educación"
    elif "music" in categories or "música" in categories:
        return "Música"
    elif any(c in categories for c in ["general", "entertainment", "entretenimiento", "family"]):
        if country == "MX":
            return "TV abierta México"
        elif country == "CO":
            return "TV abierta Colombia"
        elif country in ["GT", "SV", "HN", "NI", "CR", "PA"]:
            return "TV abierta Centroamérica"
        elif country in ["PE", "EC", "VE", "CL", "AR", "UY", "PY", "BO", "DO", "PR"]:
            return "TV abierta Sudamérica"
        else:
            return "Entretenimiento"
    return "Otros Latinos"


# ═══════════════════════════════════════════════════════════════════════
# STREAM VALIDATION (8s Timeout, 2 Retries, Max 8 Workers)
# ═══════════════════════════════════════════════════════════════════════

def validate_stream_url(url, custom_user_agent=None, custom_referrer=None):
    headers = {"User-Agent": custom_user_agent or USER_AGENT}
    if custom_referrer:
        headers["Referer"] = custom_referrer
        
    last_status = "unknown"
    latency = 0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            start = time.time()
            resp = requests.get(
                url,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
                stream=True,
            )
            # Read first 8KB to verify HLS contents
            content = resp.raw.read(8192).decode("utf-8", errors="replace")
            resp.close()
            latency = round((time.time() - start) * 1000)
            
            if resp.status_code == 200:
                if "#EXTM3U" in content or "#EXT-X-" in content:
                    return True, "online", latency
                else:
                    return False, "HTTP 200 but not valid HLS", latency
            else:
                last_status = f"HTTP {resp.status_code}"
        except requests.exceptions.Timeout:
            last_status = f"timeout (attempt {attempt})"
            latency = TIMEOUT_SECONDS * 1000
        except requests.exceptions.RequestException as e:
            last_status = f"error: {str(e)[:100]}"
            latency = 0
            
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)
            
    return False, last_status, latency


def inspect_hls_audio(stream_url, custom_user_agent=None, custom_referrer=None):
    headers = {"User-Agent": custom_user_agent or USER_AGENT}
    if custom_referrer:
        headers["Referer"] = custom_referrer
        
    try:
        resp = requests.get(
            stream_url,
            headers=headers,
            timeout=TIMEOUT_SECONDS,
            stream=True,
        )
        content = resp.raw.read(16384).decode("utf-8", errors="replace")
        resp.close()
        
        if resp.status_code != 200:
            return "unknown", "unverifiable"
            
        audio_langs = []
        for match in re.finditer(r'#EXT-X-MEDIA:.*?TYPE=AUDIO.*', content):
            media_line = match.group(0)
            lang_match = re.search(r'LANGUAGE="([^"]*)"', media_line)
            if lang_match:
                audio_langs.append(lang_match.group(1).lower())
            name_match = re.search(r'NAME="([^"]*)"', media_line)
            if name_match:
                audio_langs.append(name_match.group(1).lower())
                
        if not audio_langs:
            return "unknown", "unverifiable"
            
        spanish_indicators = ["es", "spa", "spanish", "español", "espanol"]
        portuguese_indicators = ["pt", "por", "portuguese", "português", "portugues"]
        
        has_spanish = any(any(si in lang for si in spanish_indicators) for lang in audio_langs)
        has_portuguese = any(any(pi in lang for pi in portuguese_indicators) for lang in audio_langs)
        
        if has_spanish:
            return "es", "verified"
        elif has_portuguese and not has_spanish:
            return "pt", "rejected"
        return "unknown", "unverifiable"
    except Exception:
        return "unknown", "unverifiable"


# ═══════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════

def run_import():
    print("=" * 60)
    print("  IPTV Guatemala - Descubrimiento y Clasificación de Canales")
    print("=" * 60)
    print()
    
    # Load configuration files
    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: No se encontró {CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    overrides = {}
    if os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
            overrides = json.load(f).get("overrides", {})
            
    wanted_queries = set()
    if os.path.exists(WANTED_FILE):
        try:
            with open(WANTED_FILE, "r", encoding="utf-8") as f:
                wanted_data = json.load(f)
                wanted_queries = {ch["query"].lower() for ch in wanted_data.get("channels", []) if ch.get("enabled", True)}
        except Exception:
            pass
            
    # Download metadata and M3U
    channels_map, feeds_map, countries_map = download_api_metadata()
    m3u_content = download_m3u()
    all_streams = parse_m3u(m3u_content)
    total_m3u_entries = len(all_streams)
    print(f"  Entradas analizadas en M3U: {total_m3u_entries:,}")
    
    # Group streams by base name and pre-score them
    groups = {}  # base_name -> list of candidate stream entries
    
    for stream in all_streams:
        base_name = get_base_name(stream, channels_map)
        if not base_name:
            continue
            
        score, reasons = calculate_score(stream, base_name, channels_map, feeds_map, countries_map, overrides, config)
        
        # Determine original category
        tvg_id = stream.get("tvg_id", "")
        base_id = tvg_id.split("@")[0] if tvg_id else None
        ch_meta = channels_map.get(base_id) if base_id else None
        category_orig = ch_meta["categories"][0] if ch_meta and ch_meta.get("categories") else "General"
        
        candidate = {
            "stream": stream,
            "base_name": base_name,
            "score": score,
            "reasons": reasons,
            "country": ch_meta["country"] if ch_meta else "Unknown",
            "category_original": category_orig,
            "quality": stream["resolution"],
        }
        
        groups.setdefault(base_name, []).append(candidate)
        
    # Deduplication and candidate ranking
    ranked_groups = {}
    duplicates_discarded = 0
    total_latin_candidates = 0
    
    for base_name, candidates in groups.items():
        # Step 1: Check if any candidate has LATAM region/origin with a high score (>= 100)
        has_latin_version = any(
            c["score"] >= 100 and c["country"] in ["MX", "CO", "GT", "SV", "HN", "NI", "CR", "PA", "PE", "EC", "VE", "DO", "PR", "BO", "PY", "UY", "CL", "AR"]
            for c in candidates
        )
        
        # Step 2: Apply the Spain penalty if a Latin version exists
        for c in candidates:
            if has_latin_version and (c["country"] == "ES" or "spain" in c["stream"]["display_name"].lower()):
                c["score"] -= 500
                c["reasons"].append("penalización: España cuando existe variante latinoamericana (-500)")
                
        # Sort candidates in group by score descending
        sorted_candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
        
        # Exclude completely rejected ones (score < 0)
        sorted_candidates = [c for c in sorted_candidates if c["score"] >= 0]
        if not sorted_candidates:
            continue
            
        # Count Latin candidates
        is_latin = any(
            c["score"] >= 100 or c["base_name"].lower() in wanted_queries
            for c in sorted_candidates
        )
        if is_latin:
            total_latin_candidates += 1
            
        # Limit to top 3 candidates for validation
        top_candidates = sorted_candidates[:config.get("validate_top_candidates_per_base", 3)]
        ranked_groups[base_name] = {
            "top_candidates": top_candidates,
            "all_sorted": sorted_candidates,
        }
        
        # Count discarded candidates
        duplicates_discarded += len(sorted_candidates) - 1
        
    print(f"  Candidatos latinos identificados: {total_latin_candidates}")
    
    # Filter groups that pass the minimum auto-import score OR are in wanted/overrides priority list
    groups_to_validate = {}
    for base_name, group in ranked_groups.items():
        top_score = group["top_candidates"][0]["score"]
        override = overrides.get(base_name, {})
        is_priority = (
            base_name.lower() in wanted_queries or 
            override.get("force_include", False)
        )
        
        if top_score >= config.get("minimum_auto_import_score", 140) or is_priority:
            groups_to_validate[base_name] = group
            
    print(f"  Grupos de canales base a validar: {len(groups_to_validate)}")
    
    # ── Concurrent Stream Validation ──
    # Save partial progress helper
    imported_channels = []
    report_entries = []
    duplicates_report = []
    
    lock = threading.Lock()
    
    def _save_partial():
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        sorted_imported = sorted(imported_channels, key=lambda x: x["display_name"].lower())
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
            json.dump({
                "channels": sorted_imported,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }, f_out, indent=2, ensure_ascii=False)
            
    # Save discovered_candidates.json
    discovered_list = []
    for base_name, group in groups_to_validate.items():
        for tc in group["top_candidates"]:
            discovered_list.append({
                "base_name": base_name,
                "name": tc["stream"]["display_name"],
                "tvg_id": tc["stream"]["tvg_id"],
                "score": tc["score"],
                "country": tc["country"],
                "quality": tc["quality"]
            })
    os.makedirs(os.path.dirname(CANDIDATES_FILE), exist_ok=True)
    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f_cand:
        json.dump({"candidates": discovered_list}, f_cand, indent=2, ensure_ascii=False)
        
    # We validate sequentially in 3 batches to avoid validating 2nd/3rd candidates if the 1st succeeds.
    max_candidates_to_check = config.get("validate_top_candidates_per_base", 3)
    
    # base_name -> index of candidate currently being checked (0, 1, 2)
    base_progress = {name: 0 for name in groups_to_validate}
    # base_name -> selected candidate (or None)
    base_selected = {name: None for name in groups_to_validate}
    # Calculate total potential validations
    total_to_validate = 0
    for base_name, group in groups_to_validate.items():
        total_to_validate += min(len(group["top_candidates"]), max_candidates_to_check)
        
    validated_count = 0
    count_lock = threading.Lock()
    
    print(f"  Validando candidatos con 8 workers...")
    
    for check_idx in range(max_candidates_to_check):
        # Gather candidates for this round
        candidates_to_validate = []
        for base_name, group in groups_to_validate.items():
            if base_selected[base_name] is not None:
                continue # Already found a functional one
            if check_idx < len(group["top_candidates"]):
                candidates_to_validate.append((base_name, group["top_candidates"][check_idx]))
                
        if not candidates_to_validate:
            break
            
        print(f"    [Ronda {check_idx+1}] Validando {len(candidates_to_validate)} streams en paralelo...")
        
        def validate_worker(item):
            nonlocal validated_count
            base_name, cand = item
            stream = cand["stream"]
            
            with count_lock:
                validated_count += 1
                current_idx = validated_count
                
            # Print progress indication
            print(f"    [{current_idx}/{total_to_validate}] Validando {base_name} ({cand['quality'] or 'SD'})...", flush=True)
            
            is_online, status_detail, latency = validate_stream_url(
                stream["stream_url"],
                stream.get("user_agent"),
                stream.get("referrer")
            )
            
            val_status = "online"
            if not is_online:
                val_status = "timeout" if "timeout" in status_detail.lower() else "offline"
                
            # HLS audio check if online
            language = "unknown"
            language_status = "unverifiable"
            if is_online:
                audio_lang, audio_status = inspect_hls_audio(
                    stream["stream_url"],
                    stream.get("user_agent"),
                    stream.get("referrer")
                )
                language = audio_lang
                language_status = audio_status
                if audio_lang == "pt" and audio_status == "rejected":
                    val_status = "rejected_language"
                    is_online = False
                    
            return base_name, cand, is_online, val_status, status_detail, latency, language, language_status
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(validate_worker, item) for item in candidates_to_validate]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    base_name, cand, is_online, val_status, status_detail, latency, language, language_status = fut.result()
                    
                    if is_online:
                        with lock:
                            if base_selected[base_name] is None:
                                base_selected[base_name] = {
                                    "cand": cand,
                                    "val_status": val_status,
                                    "status_detail": status_detail,
                                    "latency": latency,
                                    "language": language,
                                    "language_status": language_status
                                }
                except Exception as e:
                    print(f"      Error en validador: {e}")
                    
    # Process final selections
    for base_name, selection in base_selected.items():
        group = groups_to_validate[base_name]
        override = overrides.get(base_name, {})
        
        if selection is not None:
            cand = selection["cand"]
            sel_ch = cand["stream"]
            
            # Map clean display name
            display_name = override.get("display_name", base_name)
            category_final = classify_category(base_name, channels_map, override)
            
            entry = {
                "base_name": base_name,
                "selected_name": sel_ch["display_name"],
                "display_name": display_name,
                "tvg_id": sel_ch["tvg_id"],
                "tvg_name": sel_ch["tvg_name"],
                "tvg_logo": sel_ch["tvg_logo"],
                "country": cand["country"],
                "region": detect_region_for_candidate(cand),
                "language": selection["language"],
                "category_original": cand["category_original"],
                "category_final": category_final,
                "quality": cand["quality"],
                "stream_url": sel_ch["stream_url"],
                "source": "iptv-org",
                "score": cand["score"],
                "validation_status": selection["val_status"],
                "selection_reason": "; ".join(cand["reasons"]) + f"; Latencia {selection['latency']}ms",
                "extra_lines": sel_ch.get("extra_lines", []),
                "needs_review": len(group["top_candidates"]) > 1 and abs(group["top_candidates"][0]["score"] - group["top_candidates"][1]["score"]) < 20
            }
            
            imported_channels.append(entry)
            
            # Record duplicates discarded
            for discarded in group["all_sorted"]:
                if discarded["stream"]["stream_url"] != sel_ch["stream_url"]:
                    duplicates_report.append({
                        "base_name": base_name,
                        "selected_variant": sel_ch["display_name"],
                        "discarded_variant": discarded["stream"]["display_name"],
                        "reason": f"Calidad/score inferior ({discarded['score']} vs {cand['score']}) o stream caído."
                    })
                    
            report_entries.append({
                "query": base_name,
                "candidates_found": len(group["all_sorted"]),
                "selected": {
                    "name": sel_ch["display_name"],
                    "region": entry["region"],
                    "quality": cand["quality"],
                    "score": cand["score"],
                    "status": selection["val_status"],
                },
                "status": selection["val_status"],
                "needs_review": entry["needs_review"]
            })
        else:
            # All candidates failed
            # Select the first candidate as offline if priority/force included
            is_priority = base_name.lower() in wanted_queries or override.get("force_include", False)
            if is_priority and len(group["top_candidates"]) > 0:
                cand = group["top_candidates"][0]
                sel_ch = cand["stream"]
                display_name = override.get("display_name", base_name)
                category_final = classify_category(base_name, channels_map, override)
                
                entry = {
                    "base_name": base_name,
                    "selected_name": sel_ch["display_name"],
                    "display_name": display_name,
                    "tvg_id": sel_ch["tvg_id"],
                    "tvg_name": sel_ch["tvg_name"],
                    "tvg_logo": sel_ch["tvg_logo"],
                    "country": cand["country"],
                    "region": detect_region_for_candidate(cand),
                    "language": "unknown",
                    "category_original": cand["category_original"],
                    "category_final": category_final,
                    "quality": cand["quality"],
                    "stream_url": sel_ch["stream_url"],
                    "source": "iptv-org",
                    "score": cand["score"],
                    "validation_status": "offline",
                    "selection_reason": "Forzado por override/wanted list pero caído en validación.",
                    "extra_lines": sel_ch.get("extra_lines", []),
                    "needs_review": False
                }
                imported_channels.append(entry)
                
            report_entries.append({
                "query": base_name,
                "candidates_found": len(group["all_sorted"]),
                "selected": None,
                "status": "all_rejected_or_offline",
                "needs_review": False
            })
            
    # Apply total channel limit (maximum_total_channels)
    # Deduct 3 Guatemala channels from the total limit
    max_imported = config.get("maximum_total_channels", 250) - 3
    if len(imported_channels) > max_imported:
        print(f"  Truncando importación a {max_imported} canales (límite máximo total config)...")
        # Keep highest score ones
        imported_channels = sorted(imported_channels, key=lambda x: x["score"], reverse=True)[:max_imported]
        
    # Write final imported_channels.json
    _save_partial()
    print(f"  Archivo generado: {OUTPUT_FILE} ({len(imported_channels)} canales)")
    
    # ── Write Reports ──
    # Write reports/discovery-report.json
    os.makedirs(os.path.dirname(REPORT_JSON), exist_ok=True)
    total_imported = len(imported_channels)
    report_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_m3u_entries": total_m3u_entries,
            "total_latin_candidates": total_latin_candidates,
            "total_imported": total_imported,
            "duplicates_discarded": duplicates_discarded,
            "online": sum(1 for ch in imported_channels if ch["validation_status"] == "online"),
            "offline": sum(1 for ch in imported_channels if ch["validation_status"] in ("offline", "timeout")),
        },
        "channels": report_entries
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
        
    # Write reports/discovery-report.md
    md_report = generate_discovery_md(report_data, imported_channels)
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write(md_report)
        
    # Write reports/duplicates-report.md
    dup_report = generate_duplicates_md(duplicates_report)
    with open(DUPLICATES_REPORT_MD, "w", encoding="utf-8") as f:
        f.write(dup_report)
        
    # Print console summary
    print()
    print("=" * 60)
    print("  Resumen del Descubrimiento Automático")
    print("=" * 60)
    print(f"  Entradas analizadas:   {total_m3u_entries:,}")
    print(f"  Candidatos latinos:    {total_latin_candidates}")
    print(f"  Total importado:       {total_imported}")
    print(f"  Canales en linea:      {report_data['summary']['online']}")
    print(f"  Canales fuera/timeout: {report_data['summary']['offline']}")
    print(f"  Duplicados eliminados: {duplicates_discarded}")
    print("=" * 60)
    print()


def detect_region_for_candidate(cand):
    country = cand["country"].upper()
    if country == "MX":
        return "México"
    elif country == "CO":
        return "Colombia"
    elif country in ["GT", "SV", "HN", "NI", "CR", "PA"]:
        return "Centroamérica"
    elif country in ["PE", "EC", "VE", "CL", "AR", "UY", "PY", "BO", "DO", "PR"]:
        return "Sudamérica/Caribe"
    return "Panregional / Internacional"


def generate_discovery_md(report_data, imported):
    lines = [
        "# Reporte de Descubrimiento de Canales IPTV-org",
        "",
        f"**Generado:** {report_data['generated_at']}",
        "",
        "## Resumen General",
        "",
        f"| Métrica | Valor |",
        f"|---------|-------|",
        f"| Entradas analizadas en M3U | {report_data['summary']['total_m3u_entries']:,} |",
        f"| Candidatos latinos identificados | {report_data['summary']['total_latin_candidates']} |",
        f"| Canales importados a la playlist | {report_data['summary']['total_imported']} |",
        f"| Duplicados eliminados | {report_data['summary']['duplicates_discarded']} |",
        f"| En línea (online) | {report_data['summary']['online']} |",
        f"| Fuera de línea / Timeout | {report_data['summary']['offline']} |",
        "",
        "---",
        "",
        "## Listado de Canales Importados",
        "",
        "| Canal Base | Nombre Seleccionado | Categoría Final | Región | Calidad | Score | Estado |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]
    for ch in sorted(imported, key=lambda x: (x["category_final"], x["display_name"])):
        lines.append(
            f"| **{ch['display_name']}** | {ch['selected_name']} | {ch['category_final']} | {ch['region']} | {ch['quality'] or 'SD'} | {ch['score']} | {ch['validation_status']} |"
        )
    return "\n".join(lines)


def generate_duplicates_md(dup_report):
    lines = [
        "# Reporte de Deduplicación y Descarte de Variantes",
        "",
        "Este reporte detalla las variantes secundarias, de menor resolución o caídas que fueron descartadas en favor del stream seleccionado.",
        "",
        "| Canal Base | Variante Seleccionada | Variante Descartada | Razón del Descarte |",
        "| :--- | :--- | :--- | :--- |"
    ]
    for dup in sorted(dup_report, key=lambda x: (x["base_name"], x["discarded_variant"])):
        lines.append(
            f"| **{dup['base_name']}** | {dup['selected_variant']} | {dup['discarded_variant']} | {dup['reason']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    run_import()
