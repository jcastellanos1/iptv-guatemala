#!/usr/bin/env python3
"""
import_iptv_org.py — Importador de canales latinoamericanos desde IPTV-org.

Descarga https://iptv-org.github.io/iptv/index.m3u, filtra canales de
entretenimiento, películas, series y TV general en español latino,
y genera data/imported_channels.json + reportes.

Uso:
    python scripts/import_iptv_org.py
"""

import io
import concurrent.futures
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
WANTED_FILE = os.path.join(BASE_DIR, "data", "wanted_channels.json")
OVERRIDES_FILE = os.path.join(BASE_DIR, "data", "channel_overrides.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "imported_channels.json")
REPORT_JSON = os.path.join(BASE_DIR, "reports", "import-report.json")
REPORT_MD = os.path.join(BASE_DIR, "reports", "import-report.md")

IPTV_ORG_URL = "https://iptv-org.github.io/iptv/index.m3u"

# ─── HTTP Config ─────────────────────────────────────────────────────
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT_SECONDS = 8
MAX_RETRIES = 2
RETRY_DELAY = 1

# ─── Region accept / reject lists ───────────────────────────────────
ACCEPT_KEYWORDS = [
    "latin america", "latinoamerica", "latinoamérica", "latino", "latam",
    "mexico", "méxico", "colombia", "andes", "andino",
    "central america", "centroamerica", "centroamérica",
    "panregional", "pan regional", "hispanic",
    "spanish latin", "spanish (latin america)",
]

ACCEPT_COUNTRY_CODES = [
    "mx", "co", "gt", "sv", "hn", "ni", "cr", "pa",
    "pe", "ec", "bo", "py", "uy", "ve", "do", "pr", "latam",
]

REJECT_KEYWORDS = [
    "brazil", "brasil", "portuguese", "portugal",
    "spain", "españa",
    "asia", "indonesia", "india", "africa",
    "romania", "bulgaria", "czech", "poland", "hungary",
    "germany", "france", "italy",
    "uk", "adriatic", "cee", "balkans", "balkan",
    "russia", "turkey",
]

# Lower-priority but not fully rejected
LOWER_PRIORITY_KEYWORDS = ["argentina", "chile"]


# ═══════════════════════════════════════════════════════════════════════
# M3U PARSER
# ═══════════════════════════════════════════════════════════════════════

def parse_m3u(content):
    """
    Parse extended M3U content into a list of channel dicts.
    
    Handles:
    - Quoted attributes in #EXTINF lines
    - Display name after the last comma outside quotes
    - #EXTVLCOPT and #EXTHTTP lines
    - User-Agent and Referer extraction
    - Resolution detection in names
    """
    channels = []
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    
    i = 0
    total_lines = len(lines)
    
    while i < total_lines:
        line = lines[i].strip()
        
        if not line.startswith("#EXTINF"):
            i += 1
            continue
        
        # ── Parse #EXTINF line ──
        extinf_line = line
        
        # Extract attributes using regex for quoted values
        attrs = {}
        for match in re.finditer(r'([a-zA-Z_-]+)="([^"]*)"', extinf_line):
            key = match.group(1).lower().replace("-", "_")
            attrs[key] = match.group(2)
        
        # Extract display name: everything after the last comma that's outside quotes
        display_name = _extract_display_name(extinf_line)
        
        # ── Collect extra lines (#EXTVLCOPT, #EXTHTTP) ──
        extra_lines = []
        i += 1
        while i < total_lines:
            next_line = lines[i].strip()
            if next_line.startswith("#EXTVLCOPT:") or next_line.startswith("#EXTHTTP:"):
                extra_lines.append(next_line)
                i += 1
            else:
                break
        
        # ── Get the stream URL ──
        stream_url = ""
        if i < total_lines:
            candidate = lines[i].strip()
            if candidate and not candidate.startswith("#"):
                stream_url = candidate
                i += 1
        
        if not stream_url:
            continue
        
        # ── Extract user-agent and referrer from extra lines ──
        user_agent = None
        referrer = None
        for el in extra_lines:
            if "http-user-agent=" in el.lower():
                user_agent = el.split("=", 1)[1] if "=" in el else None
            elif "http-referrer=" in el.lower() or "http-referer=" in el.lower():
                referrer = el.split("=", 1)[1] if "=" in el else None
        
        # ── Detect resolution ──
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
    """
    Extract the display name from an #EXTINF line.
    The display name is everything after the last comma that is NOT inside quotes.
    """
    # Find the position after #EXTINF:duration
    # Pattern: #EXTINF:-1 attr="val" attr="val",...,Display Name
    in_quotes = False
    last_comma_pos = -1
    
    for idx, ch in enumerate(extinf_line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ',' and not in_quotes:
            last_comma_pos = idx
    
    if last_comma_pos >= 0:
        return extinf_line[last_comma_pos + 1:].strip()
    
    # Fallback: try to get name from tvg-name attribute
    match = re.search(r'tvg-name="([^"]*)"', extinf_line)
    if match:
        return match.group(1)
    
    return ""


def _detect_resolution(name):
    """Detect resolution from channel name."""
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
        return "720p"  # HD typically implies 720p
    elif " sd" in name_lower or "(sd)" in name_lower:
        return "480p"
    return ""


# ═══════════════════════════════════════════════════════════════════════
# NAME NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════

def normalize_name(name):
    """
    Normalize a channel name for comparison.
    Removes accents, resolution tags, parenthetical content, collapses whitespace.
    """
    # Convert to lowercase
    s = name.lower()
    # Remove accents via NFKD decomposition
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # Remove resolution tags
    s = re.sub(r'\b(1080[pi]|720p|480p|360p|hd|sd|fhd|uhd|4k)\b', '', s)
    # Remove parenthetical content
    s = re.sub(r'\([^)]*\)', '', s)
    # Remove brackets content
    s = re.sub(r'\[[^\]]*\]', '', s)
    # Collapse hyphens and underscores to spaces
    s = re.sub(r'[-_]+', ' ', s)
    # Collapse multiple spaces
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ═══════════════════════════════════════════════════════════════════════
# CHANNEL MATCHING
# ═══════════════════════════════════════════════════════════════════════

def build_query_pattern(query):
    """
    Build a word-boundary regex pattern for matching a channel query.
    Handles special characters in channel names like & in A&E.
    """
    normalized_query = normalize_name(query)
    # Escape regex special characters
    escaped = re.escape(normalized_query)
    # Build word-boundary pattern
    pattern = r'(?:^|\b)' + escaped + r'(?:\b|$)'
    return pattern


def matches_blocked_terms(name, blocked_terms):
    """Check if a channel name contains any blocked terms."""
    name_lower = name.lower()
    for term in blocked_terms:
        if term.lower() in name_lower:
            return True
    return False


def is_secondary_channel(display_name, query):
    """
    Check if a channel is a secondary/variant channel when the primary was requested.
    E.g., 'History 2' when 'History' was requested.
    """
    normalized_display = normalize_name(display_name)
    normalized_query = normalize_name(query)
    
    # Check for numbered suffixes: "History 2", "Discovery 2", etc.
    pattern = r'(?:^|\b)' + re.escape(normalized_query) + r'\s+(\d+)(?:\b|$)'
    match = re.search(pattern, normalized_display)
    if match:
        num = int(match.group(1))
        if num >= 2:
            return True
    
    return False


def find_candidates(query, all_channels, overrides):
    """
    Find all channels from the M3U that match the query.
    Returns list of (channel, match_type) tuples.
    """
    candidates = []
    query_pattern = build_query_pattern(query)
    blocked_terms = []
    
    # Get overrides for this query
    override = overrides.get(query, {})
    blocked_terms = override.get("blocked_terms", [])
    preferred_name = override.get("preferred_name")
    selected_tvg_id = override.get("selected_tvg_id")
    
    # If a specific tvg_id is forced, only look for that
    if selected_tvg_id:
        for ch in all_channels:
            if ch["tvg_id"] == selected_tvg_id:
                candidates.append((ch, "forced_tvg_id"))
        return candidates
    
    for ch in all_channels:
        display = ch["display_name"]
        tvg_name = ch["tvg_name"]
        tvg_id = ch["tvg_id"]
        
        # Check against blocked terms using display name, tvg_name, and tvg_id
        full_text = f"{display} {tvg_name} {tvg_id}"
        if matches_blocked_terms(full_text, blocked_terms):
            continue
        
        # Normalize names for matching
        norm_display = normalize_name(display)
        norm_tvg = normalize_name(tvg_name)
        
        matched = False
        match_type = "none"
        
        # Check if preferred_name matches exactly
        if preferred_name and preferred_name.lower() in display.lower():
            matched = True
            match_type = "preferred_exact"
        
        # Check display name
        if not matched and re.search(query_pattern, norm_display):
            matched = True
            match_type = "display_name"
        
        # Check tvg-name
        if not matched and re.search(query_pattern, norm_tvg):
            matched = True
            match_type = "tvg_name"
        
        # Check tvg-id (with dots and underscores normalized)
        if not matched:
            norm_id = normalize_name(tvg_id.replace(".", " "))
            if re.search(query_pattern, norm_id):
                matched = True
                match_type = "tvg_id"
        
        if matched:
            candidates.append((ch, match_type))
    
    return candidates


# ═══════════════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════════════

def score_candidate(channel, query, match_type):
    """
    Assign a score to a candidate channel based on region, quality,
    metadata completeness, and match quality.
    """
    score = 0
    reasons = []
    
    display = channel["display_name"]
    tvg_name = channel["tvg_name"]
    tvg_id = channel["tvg_id"]
    full_text = f"{display} {tvg_name} {tvg_id}".lower()
    
    norm_display = normalize_name(display)
    norm_query = normalize_name(query)
    
    # ── Base match score ──
    if norm_display == norm_query or norm_display.startswith(norm_query + " "):
        score += 100
        reasons.append("coincidencia exacta del nombre base (+100)")
    elif match_type == "preferred_exact":
        score += 100
        reasons.append("coincidencia con nombre preferido (+100)")
    elif match_type == "display_name":
        score += 80
        reasons.append("coincidencia en nombre visible (+80)")
    elif match_type == "tvg_name":
        score += 70
        reasons.append("coincidencia en tvg-name (+70)")
    elif match_type == "tvg_id":
        score += 60
        reasons.append("coincidencia en tvg-id (+60)")
    elif match_type == "forced_tvg_id":
        score += 200
        reasons.append("tvg-id forzado por override (+200)")
    
    # ── Region scoring ──
    for kw in ["latin america", "latinoamerica", "latinoamérica", "latam"]:
        if kw in full_text:
            score += 60
            reasons.append(f"región Latin America/LATAM (+60)")
            break
    else:
        for kw in ["mexico", "méxico"]:
            if kw in full_text:
                score += 50
                reasons.append("región Mexico (+50)")
                break
        else:
            if "colombia" in full_text:
                score += 45
                reasons.append("región Colombia (+45)")
            elif any(kw in full_text for kw in ["andes", "andino"]):
                score += 40
                reasons.append("región Andes (+40)")
            elif any(kw in full_text for kw in ["centroamerica", "centroamérica", "central america"]):
                score += 35
                reasons.append("región Centroamérica (+35)")
            elif any(kw in full_text for kw in ["peru", "perú", "ecuador"]):
                score += 30
                reasons.append("región hispanoamericana (+30)")
    
    # ── Quality scoring ──
    resolution = channel.get("resolution", "")
    if resolution == "1080p":
        score += 20
        reasons.append("calidad 1080p (+20)")
    elif resolution == "720p":
        score += 10
        reasons.append("calidad 720p (+10)")
    
    # ── Metadata scoring ──
    if channel.get("tvg_logo"):
        score += 10
        reasons.append("tiene logo (+10)")
    if channel.get("tvg_id"):
        score += 10
        reasons.append("tiene tvg-id (+10)")
    if channel.get("stream_url", "").startswith("https://"):
        score += 10
        reasons.append("usa HTTPS (+10)")
    
    # ── PENALTIES ──
    
    # Hard reject: wrong region/language
    for kw in ["brazil", "brasil", "portuguese", "portugal"]:
        if kw in full_text:
            score -= 1000
            reasons.append(f"penalización: {kw} (-1000)")
            break
    
    for kw in ["asia", "indonesia", "india"]:
        if kw in full_text:
            score -= 1000
            reasons.append(f"penalización: {kw} (-1000)")
            break
    
    for kw in ["romania", "bulgaria", "czech", "poland", "hungary",
                "germany", "france", "italy", "adriatic", "cee",
                "balkans", "balkan", "russia", "turkey"]:
        if kw in full_text:
            score -= 1000
            reasons.append(f"penalización: Europa/otra región ({kw}) (-1000)")
            break
    
    # UK penalty
    if re.search(r'\buk\b', full_text):
        score -= 1000
        reasons.append("penalización: UK (-1000)")
    
    # Spain penalty (less severe than Asia/Brazil)
    for kw in ["spain", "españa"]:
        if kw in full_text:
            score -= 500
            reasons.append(f"penalización: {kw} (-500)")
            break
    
    # Argentina/Chile: lower priority
    if "argentina" in full_text:
        score -= 100
        reasons.append("penalización: Argentina (prioridad inferior) (-100)")
    if "chile" in full_text:
        score -= 100
        reasons.append("penalización: Chile (prioridad inferior) (-100)")
    
    # Secondary channel penalty
    if is_secondary_channel(display, query):
        score -= 200
        reasons.append("penalización: canal secundario (-200)")
    
    # "Sports" penalty when not searching for sports
    if "sports" in full_text and "sports" not in query.lower():
        score -= 500
        reasons.append("penalización: contiene 'Sports' no solicitado (-500)")
    
    # "Black" / alternate themed penalty
    for kw in ["black", "edge"]:
        if kw in full_text and kw not in query.lower():
            score -= 300
            reasons.append(f"penalización: variante '{kw}' no solicitada (-300)")
            break
    
    # Clearly English feed penalty
    if "usa english" in full_text or "english" in full_text:
        score -= 500
        reasons.append("penalización: feed en inglés (-500)")
    
    # Africa penalty
    if "africa" in full_text:
        score -= 1000
        reasons.append("penalización: Africa (-1000)")
    
    return score, reasons


def detect_region(channel):
    """Detect the region from channel metadata."""
    full_text = f"{channel['display_name']} {channel['tvg_name']} {channel['tvg_id']}".lower()
    
    for kw in ["latin america", "latinoamerica", "latinoamérica", "latam"]:
        if kw in full_text:
            return "Latin America"
    for kw in ["mexico", "méxico"]:
        if kw in full_text:
            return "Mexico"
    if "colombia" in full_text:
        return "Colombia"
    for kw in ["andes", "andino"]:
        if kw in full_text:
            return "Andes"
    for kw in ["centroamerica", "centroamérica", "central america"]:
        if kw in full_text:
            return "Centroamérica"
    if "argentina" in full_text:
        return "Argentina"
    if "chile" in full_text:
        return "Chile"
    for kw in ["peru", "perú"]:
        if kw in full_text:
            return "Perú"
    if "ecuador" in full_text:
        return "Ecuador"
    
    # Check country codes in tvg_id
    tvg_id_lower = channel["tvg_id"].lower()
    for code in ACCEPT_COUNTRY_CODES:
        if f".{code}" in tvg_id_lower or tvg_id_lower.endswith(f".{code}"):
            return code.upper()
    
    return "Unknown"


# ═══════════════════════════════════════════════════════════════════════
# HLS AUDIO INSPECTION
def inspect_hls_audio(stream_url, custom_user_agent=None, custom_referrer=None):
    """
    Inspect an HLS stream's master playlist for audio language tags.
    Returns: ("es", "verified") | ("pt", "rejected") | ("unknown", "unverifiable")
    """
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
        # Read only first 16KB
        content = resp.raw.read(16384).decode("utf-8", errors="replace")
        resp.close()
        
        if resp.status_code != 200:
            return "unknown", "unverifiable"
        
        # Look for EXT-X-MEDIA audio tags
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
        
        # Check for Spanish
        spanish_indicators = ["es", "spa", "spanish", "español", "espanol"]
        portuguese_indicators = ["pt", "por", "portuguese", "português", "portugues"]
        
        has_spanish = any(any(si in lang for si in spanish_indicators) for lang in audio_langs)
        has_portuguese = any(any(pi in lang for pi in portuguese_indicators) for lang in audio_langs)
        
        if has_spanish:
            return "es", "verified"
        elif has_portuguese and not has_spanish:
            return "pt", "rejected"
        else:
            return "unknown", "unverifiable"
    
    except Exception:
        return "unknown", "unverifiable"


# ═══════════════════════════════════════════════════════════════════════
# STREAM VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def validate_stream_url(url, custom_user_agent=None, custom_referrer=None):
    """
    Validate that a stream URL is accessible and returns valid HLS content.
    Returns (is_online, status_detail, latency_ms).
    """
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
            # Read only first 8KB
            content = resp.raw.read(8192).decode("utf-8", errors="replace")
            resp.close()
            latency = round((time.time() - start) * 1000)
            
            if resp.status_code == 200:
                if "#EXTM3U" in content or "#EXT-X-" in content:
                    return True, "online", latency
                else:
                    return False, f"HTTP 200 but not valid HLS", latency
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


# ═══════════════════════════════════════════════════════════════════════
# SELECTION ENGINE
# ═══════════════════════════════════════════════════════════════════════

def select_best_channel(candidates_scored):
    """
    From scored candidates, select the best one.
    If top 2 are within 20 points, flag for manual review.
    
    Returns (selected, needs_review, all_scored).
    """
    if not candidates_scored:
        return None, False, []
    
    # Sort by score descending
    sorted_candidates = sorted(candidates_scored, key=lambda x: x["score"], reverse=True)
    
    best = sorted_candidates[0]
    
    # If score is negative, reject all
    if best["score"] < 0:
        return None, False, sorted_candidates
    
    # Check if top 2 are too close
    needs_review = False
    if len(sorted_candidates) >= 2:
        second = sorted_candidates[1]
        if second["score"] > 0 and (best["score"] - second["score"]) < 20:
            needs_review = True
    
    return best, needs_review, sorted_candidates


def select_best_quality(candidates_same_region):
    """
    From candidates in the same region, pick the best quality.
    Priority: 1080p > 720p > unspecified > 480p
    """
    quality_order = {"1080p": 0, "720p": 1, "": 2, "480p": 3, "360p": 4}
    
    sorted_by_quality = sorted(
        candidates_same_region,
        key=lambda x: quality_order.get(x.get("resolution", ""), 2)
    )
    
    return sorted_by_quality[0] if sorted_by_quality else None


# ═══════════════════════════════════════════════════════════════════════
# MAIN IMPORT LOGIC
# ═══════════════════════════════════════════════════════════════════════

def download_m3u():
    """Download the IPTV-org master M3U list."""
    print(f"  Descargando lista de IPTV-org...")
    print(f"  URL: {IPTV_ORG_URL}")
    
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(IPTV_ORG_URL, headers=headers, timeout=60)
        resp.raise_for_status()
        content = resp.text
        print(f"  Descargados {len(content):,} bytes ({content.count(chr(10)):,} lineas)")
        return content
    except requests.RequestException as e:
        print(f"  ERROR: No se pudo descargar la lista: {e}")
        sys.exit(1)


def run_import():
    """Main import pipeline."""
    print("=" * 60)
    print("  IPTV Guatemala - Importador IPTV-org")
    print("=" * 60)
    print()
    
    # Load wanted channels
    with open(WANTED_FILE, "r", encoding="utf-8") as f:
        wanted_data = json.load(f)
    wanted_channels = [ch for ch in wanted_data["channels"] if ch.get("enabled", True)]
    total_wanted = len(wanted_channels)
    print(f"  Canales deseados: {total_wanted}")
    
    # Load overrides
    overrides = {}
    if os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
            overrides = json.load(f).get("overrides", {})
        print(f"  Overrides cargados: {len(overrides)}")
    
    # Download and parse M3U
    m3u_content = download_m3u()
    all_channels = parse_m3u(m3u_content)
    print(f"  Canales parseados de IPTV-org: {len(all_channels):,}")
    print()
    
    imported = []
    report_entries = []
    
    lock = threading.Lock()
    progress_counter = 0
    
    def _save_partial():
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        # Sort imported by query name to keep it neat
        sorted_imported = sorted(imported, key=lambda x: x["query"].lower())
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
            json.dump({
                "channels": sorted_imported,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }, f_out, indent=2, ensure_ascii=False)

    def process_channel(wanted):
        nonlocal progress_counter
        query = wanted["query"]
        group_override = wanted.get("group_override", "Entretenimiento")
        
        with lock:
            progress_counter += 1
            current_progress = progress_counter
            
        print(f"[{current_progress}/{total_wanted}] Validando {query}...")
        
        try:
            # Find candidates
            candidates = find_candidates(query, all_channels, overrides)
            
            if not candidates:
                print(f"     [{query}] [!] No se encontro ninguna coincidencia")
                with lock:
                    report_entries.append({
                        "query": query,
                        "candidates_found": 0,
                        "candidates_rejected": [],
                        "selected": None,
                        "status": "not_found",
                        "needs_review": False,
                    })
                    _save_partial()
                return
            
            # Score each candidate
            scored = []
            rejected = []
            
            for ch, match_type in candidates:
                ch_score, ch_reasons = score_candidate(ch, query, match_type)
                
                entry = {
                    "channel": ch,
                    "match_type": match_type,
                    "score": ch_score,
                    "reasons": ch_reasons,
                    "region": detect_region(ch),
                    "resolution": ch.get("resolution", ""),
                }
                
                if ch_score < 0:
                    rejected.append(entry)
                else:
                    scored.append(entry)
            
            # Select best
            selected, needs_review, all_sorted = select_best_channel(scored)
            
            if selected is None:
                print(f"     [{query}] [!] Todos los candidatos fueron rechazados")
                with lock:
                    report_entries.append({
                        "query": query,
                        "candidates_found": len(candidates),
                        "candidates_rejected": [
                            {
                                "name": r["channel"]["display_name"],
                                "reason": "; ".join(r["reasons"]),
                                "score": r["score"],
                                "region": r["region"],
                            }
                            for r in rejected
                        ],
                        "selected": None,
                        "status": "all_rejected",
                        "needs_review": False,
                    })
                    _save_partial()
                return
            
            sel_ch = selected["channel"]
            
            # Validate stream
            is_online, status_detail, latency = validate_stream_url(
                sel_ch["stream_url"],
                sel_ch.get("user_agent"),
                sel_ch.get("referrer"),
            )
            
            if is_online:
                validation_status = "online"
            elif "timeout" in status_detail.lower():
                validation_status = "timeout"
            else:
                validation_status = "offline"
            
            # If offline or timeout, try next best candidate (only if score >= 100)
            if not is_online and len(all_sorted) > 1:
                for alt in all_sorted[1:3]:  # Try next 2
                    if alt["score"] < 100:
                        continue
                    alt_ch = alt["channel"]
                    alt_online, alt_detail, alt_latency = validate_stream_url(
                        alt_ch["stream_url"],
                        alt_ch.get("user_agent"),
                        alt_ch.get("referrer"),
                    )
                    if alt_online:
                        selected = alt
                        sel_ch = alt_ch
                        is_online = True
                        validation_status = "online"
                        status_detail = alt_detail
                        latency = alt_latency
                        break
                    elif "timeout" in alt_detail.lower() and validation_status != "online":
                        validation_status = "timeout"
            
            # Inspect HLS audio if online
            language = "unknown"
            language_status = "unverifiable"
            if is_online:
                try:
                    language, language_status = inspect_hls_audio(
                        sel_ch["stream_url"],
                        sel_ch.get("user_agent"),
                        sel_ch.get("referrer"),
                    )
                    if language == "pt" and language_status == "rejected":
                        validation_status = "rejected_language"
                        # Try to find another candidate
                        for alt in all_sorted:
                            if alt is selected:
                                continue
                            if alt["score"] < 0:
                                continue
                            alt_ch = alt["channel"]
                            alt_lang, alt_ls = inspect_hls_audio(
                                alt_ch["stream_url"],
                                alt_ch.get("user_agent"),
                                alt_ch.get("referrer"),
                            )
                            if alt_lang != "pt":
                                selected = alt
                                sel_ch = alt_ch
                                language = alt_lang
                                language_status = alt_ls
                                validation_status = "online"
                                break
                except Exception as e:
                    pass
            
            # Build imported entry
            imported_entry = {
                "query": query,
                "selected_name": sel_ch["display_name"],
                "tvg_id": sel_ch["tvg_id"],
                "tvg_name": sel_ch["tvg_name"],
                "tvg_logo": sel_ch["tvg_logo"],
                "group_title": group_override,
                "region": selected["region"],
                "quality": sel_ch.get("resolution", ""),
                "language": language,
                "language_status": language_status,
                "stream_url": sel_ch["stream_url"],
                "source": "iptv-org",
                "score": selected["score"],
                "validation_status": validation_status,
                "selection_reason": "; ".join(selected["reasons"]),
                "extra_lines": sel_ch.get("extra_lines", []),
                "needs_review": needs_review,
            }
            
            with lock:
                imported.append(imported_entry)
                report_entries.append({
                    "query": query,
                    "candidates_found": len(candidates),
                    "candidates_rejected": [
                        {
                            "name": r["channel"]["display_name"],
                            "reason": "; ".join(r["reasons"]),
                            "score": r["score"],
                            "region": r["region"],
                        }
                        for r in rejected
                    ],
                    "all_scored": [
                        {
                            "name": s["channel"]["display_name"],
                            "score": s["score"],
                            "region": s["region"],
                            "resolution": s["resolution"],
                        }
                        for s in all_sorted
                    ],
                    "selected": {
                        "name": sel_ch["display_name"],
                        "region": selected["region"],
                        "quality": sel_ch.get("resolution", ""),
                        "score": selected["score"],
                        "status": validation_status,
                    },
                    "status": validation_status,
                    "needs_review": needs_review,
                })
                _save_partial()
                
        except Exception as e:
            print(f"     [{query}] [ERROR CRITICO] Ocurrio un error al procesar el canal: {e}")
            with lock:
                report_entries.append({
                    "query": query,
                    "candidates_found": 0,
                    "candidates_rejected": [],
                    "selected": None,
                    "status": f"error: {str(e)[:100]}",
                    "needs_review": False,
                })
                _save_partial()

    # Run in a thread pool of max 8 workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(process_channel, wanted) for wanted in wanted_channels]
        concurrent.futures.wait(futures)
        
    # ── Write final reports ──
    
    # Write report-json
    os.makedirs(os.path.dirname(REPORT_JSON), exist_ok=True)
    report_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "wanted": len(wanted_channels),
            "found": len(imported),
            "not_found": len(wanted_channels) - len(imported),
            "online": sum(1 for ch in imported if ch["validation_status"] == "online"),
            "offline": sum(1 for ch in imported if ch["validation_status"] == "offline"),
            "needs_review": sum(1 for ch in imported if ch.get("needs_review")),
        },
        "channels": report_entries,
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    print(f"  Reporte JSON: {REPORT_JSON}")
    
    # import-report.md
    md = generate_report_md(report_data, imported)
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"  Reporte MD: {REPORT_MD}")
    
    # Summary
    print()
    print("=" * 60)
    print("  Resumen de importacion")
    print("=" * 60)
    print(f"  Canales solicitados:   {len(wanted_channels)}")
    print(f"  Canales encontrados:   {len(imported)}")
    print(f"  Canales en linea:      {report_data['summary']['online']}")
    print(f"  Canales fuera de linea:{report_data['summary']['offline']}")
    print(f"  No encontrados:        {report_data['summary']['not_found']}")
    print(f"  Requieren revision:    {report_data['summary']['needs_review']}")
    print()
    
    not_found = [
        e["query"] for e in report_entries
        if e.get("status") in ("not_found", "all_rejected")
    ]
    if not_found:
        print("  Canales no encontrados:")
        for nf in not_found:
            print(f"    - {nf}")
    
    print()
    return imported


def generate_report_md(report_data, imported):
    """Generate the human-readable markdown report."""
    lines = [
        "# Reporte de Importación IPTV-org",
        "",
        f"**Generado:** {report_data['generated_at']}",
        "",
        "## Resumen",
        "",
        f"| Métrica | Valor |",
        f"|---------|-------|",
        f"| Canales solicitados | {report_data['summary']['wanted']} |",
        f"| Canales encontrados | {report_data['summary']['found']} |",
        f"| No encontrados | {report_data['summary']['not_found']} |",
        f"| En línea | {report_data['summary']['online']} |",
        f"| Fuera de línea | {report_data['summary']['offline']} |",
        f"| Requieren revisión | {report_data['summary']['needs_review']} |",
        "",
        "---",
        "",
        "## Detalle por Canal",
        "",
    ]
    
    for entry in report_data["channels"]:
        query = entry["query"]
        lines.append(f"### {query}")
        lines.append("")
        
        if entry.get("selected"):
            sel = entry["selected"]
            lines.append("**Seleccionado:**")
            lines.append(f"- **{sel['name']}**")
            lines.append(f"- Región: {sel['region']}")
            lines.append(f"- Calidad: {sel.get('quality') or 'no especificada'}")
            lines.append(f"- Estado: {sel['status']}")
            lines.append(f"- Score: {sel['score']}")
        else:
            status = entry.get("status", "unknown")
            if status == "not_found":
                lines.append("**No encontrado en la lista de IPTV-org.**")
            elif status == "all_rejected":
                lines.append("**Todos los candidatos fueron rechazados.**")
        
        lines.append("")
        
        # Rejected
        if entry.get("candidates_rejected"):
            lines.append("**Rechazados:**")
            for rej in entry["candidates_rejected"]:
                lines.append(f"- ~~{rej['name']}~~ — {rej['reason']} (score: {rej['score']})")
            lines.append("")
        
        # All scored candidates
        if entry.get("all_scored") and len(entry["all_scored"]) > 1:
            lines.append("**Otros candidatos:**")
            for cand in entry["all_scored"][1:5]:  # Show top 5
                lines.append(f"- {cand['name']} — score: {cand['score']}, "
                             f"región: {cand['region']}, calidad: {cand.get('resolution') or 'n/a'}")
            lines.append("")
        
        if entry.get("needs_review"):
            lines.append("> ⚠️ **Requiere revisión manual:** Los dos mejores candidatos tienen una diferencia menor a 20 puntos.")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    return "\n".join(lines)


if __name__ == "__main__":
    run_import()
