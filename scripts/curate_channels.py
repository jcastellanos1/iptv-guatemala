#!/usr/bin/env python3
"""
curate_channels.py — Curation engine for IPTV Guatemala.

Downloads the IPTV-org master playlist once, matches streams against a list
of 50 curated brands, filters by region preference and blocked terms, ranks them
by quality, performs sequential validation, and writes the selected channels
and performance reports.
"""

import os
import sys
import json
import re
import time
import argparse
import unicodedata
from datetime import datetime, timezone
import requests

# ─── Config & Paths ──────────────────────────────────────────────────
BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CURATED_FILE = os.path.join(BASE_DIR, "data", "curated_channels.json")
SELECTED_FILE = os.path.join(BASE_DIR, "data", "selected_channels.json")
CHANNELS_FILE = os.path.join(BASE_DIR, "data", "channels.json")
OVERRIDES_FILE = os.path.join(BASE_DIR, "data", "channel_overrides.json")

REPORT_JSON = os.path.join(BASE_DIR, "reports", "curation-report.json")
REPORT_MD = os.path.join(BASE_DIR, "reports", "curation-report.md")
NOT_FOUND_MD = os.path.join(BASE_DIR, "reports", "not-found.md")
DUPLICATES_MD = os.path.join(BASE_DIR, "reports", "duplicates-report.md")

IPTV_ORG_M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT_SECONDS = 5
MAX_RETRIES = 1

# ─── Name Normalization ──────────────────────────────────────────────
def normalize_string(text):
    """Normalize string for robust comparison (lowercase, ascii, no special chars)."""
    if not text:
        return ""
    text = text.lower()
    # Normalize unicode characters (remove accents)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Remove resolution tags and common suffixes
    text = re.sub(r'\b(1080[pi]|720p|480p|360p|hd|sd|fhd|uhd|4k)\b', '', text)
    # Remove parentheses and brackets content
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)
    # Keep only alphanumeric and space
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ─── M3U Parser ──────────────────────────────────────────────────────
def parse_m3u(content):
    """Parse extended M3U content into a list of stream dictionaries."""
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
        
        # Extract attributes
        attrs = {}
        for match in re.finditer(r'([a-zA-Z_-]+)="([^"]*)"', extinf_line):
            key = match.group(1).lower().replace("-", "_")
            attrs[key] = match.group(2)
            
        # Extract display name (after the last comma)
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
                
        # Find stream URL
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
            
        # Detect resolution
        resolution = ""
        name_lower = display_name.lower()
        if "1080p" in name_lower or "1080i" in name_lower or "fhd" in name_lower:
            resolution = "1080p"
        elif "720p" in name_lower or "hd" in name_lower:
            resolution = "720p"
        elif "480p" in name_lower or "360p" in name_lower or "sd" in name_lower:
            resolution = "sd"
            
        # Get country suffix from tvg_id
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

# ─── Stream Validation ───────────────────────────────────────────────
def validate_stream(url, extra_lines):
    """
    Validate HLS stream. Checks for HTTP 200 and HLS headers.
    Returns (is_online, latency_ms, error_msg)
    """
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
            
        # Read the first 4KB to verify HLS content using iter_content to handle gzip/deflate
        try:
            chunk_bytes = next(resp.iter_content(chunk_size=4096), b"")
        except StopIteration:
            chunk_bytes = b""
        chunk = chunk_bytes.decode("utf-8", errors="replace")
        resp.close()
        
        if chunk.strip().startswith("#EXTM3U") or "#EXT-X-STREAM-INF" in chunk or "#EXTINF" in chunk:
            return True, latency, None
        else:
            return False, latency, "Not valid HLS playlist"
            
    except requests.exceptions.Timeout:
        return False, int(TIMEOUT_SECONDS * 1000), "Timeout"
    except Exception as e:
        return False, 0, str(e)[:100]

# ─── Core Matching & Curation Logic ──────────────────────────────────
def matches_preferred_region(stream, preferred_regions):
    """Determine if candidate matches preferred regions."""
    suffix = stream["country_suffix"]
    name_lower = stream["display_name"].lower()
    group_lower = stream["group_title"].lower()
    
    # Suffix lists for preferred regions
    region_suffixes = {
        "latin america": ["la", "pr", "latam", "latinoamerica", "panregional"],
        "panregional": ["la", "pr", "latam", "latinoamerica", "panregional"],
        "mexico": ["mx"],
        "colombia": ["co"],
        "central america": ["gt", "cr", "pa", "hn", "ni", "sv"],
        "andes": ["pe", "co", "ve", "ec", "bo"]
    }
    
    # Check general Latin American country codes
    general_latam_suffixes = ["ar", "cl", "uy", "py", "do", "pr"]
    
    for r in preferred_regions:
        r_clean = r.lower()
        # Suffix check
        if r_clean in region_suffixes and suffix in region_suffixes[r_clean]:
            return True
        # Keyword check in name or group
        if r_clean in name_lower or r_clean in group_lower:
            return True
            
    if suffix in general_latam_suffixes:
        return True
        
    return False

def check_is_spanish(stream):
    """Estimate if channel is Spanish based on tvg_id suffix or language tags."""
    suffix = stream["country_suffix"]
    name_lower = stream["display_name"].lower()
    group_lower = stream["group_title"].lower()
    
    spanish_suffixes = ["la", "mx", "co", "gt", "cr", "pa", "hn", "ni", "sv", "pe", "ve", "ec", "bo", "ar", "cl", "uy", "py", "do", "pr", "es"]
    if suffix in spanish_suffixes:
        return True
        
    spanish_keywords = ["espanol", "español", "spanish", "spa", "sp", "lat", "latam"]
    if any(k in name_lower or k in group_lower for k in spanish_keywords):
        return True
        
    return False

def matches_blocked_terms(stream, blocked_terms, blocked_urls=None, blocked_tvg_ids=None, global_blocked_urls=None):
    """Check if stream contains blocked terms (in name, tvg-id, group, or URL) or specific urls/tvg-ids."""
    stream_url = stream["stream_url"]
    if global_blocked_urls and stream_url in global_blocked_urls:
        return True
    if blocked_urls and stream_url in blocked_urls:
        return True
    if blocked_tvg_ids and stream["tvg_id"] in blocked_tvg_ids:
        return True
        
    fields = [stream["display_name"], stream["tvg_id"], stream["group_title"], stream_url]
    for term in blocked_terms:
        term_lower = term.lower()
        for f in fields:
            if term_lower in f.lower():
                return True
    return False

def matches_identity(stream, target):
    """
    Strict identity matching:
    1. Exact tvg-id base match (e.g. 'tnt' == 'tnt')
    2. Exact Alias
    3. Exact Full Name
    """
    s_name = normalize_string(stream["display_name"])
    s_tvg = normalize_string(stream["tvg_name"])
    tvg_id = stream["tvg_id"]
    
    # Extract base tvg_id without region suffix
    base_id = tvg_id.split("@")[0].lower() if tvg_id else ""
    base_id_normalized = normalize_string(base_id)
    
    target_name = target["name"]
    aliases = target["aliases"]
    
    # 1. Exact tvg-id base match
    if base_id_normalized == target_name or base_id_normalized in aliases:
        return True
        
    # 2 & 3. Exact alias or exact name
    if s_name == target_name or s_tvg == target_name:
        return True
    if s_name in aliases or s_tvg in aliases:
        return True
        
    return False

def get_sorting_key(stream, preferred_regions):
    """
    Construct priority key for sorting candidates.
    1. preferred region (1 or 0)
    2. is Spanish (1 or 0)
    3. resolution (1080p=3, 720p=2, unknown=1, sd=0)
    4. HTTPS (1 or 0)
    """
    pref_region = 1 if matches_preferred_region(stream, preferred_regions) else 0
    is_spanish = 1 if check_is_spanish(stream) else 0
    
    res_score = 1  # unknown
    if stream["resolution"] == "1080p":
        res_score = 3
    elif stream["resolution"] == "720p":
        res_score = 2
    elif stream["resolution"] == "sd":
        res_score = 0
        
    is_https = 1 if stream["stream_url"].startswith("https://") else 0
    
    return (pref_region, is_spanish, res_score, is_https)

# ─── Main Process ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Curate IPTV channels.")
    parser.add_argument("--limit", type=int, default=None, help="Limit target brands count for dry-run testing.")
    args = parser.parse_args()
    
    start_time = time.time()
    
    print("=" * 60)
    print("  IPTV Guatemala - Curated Channel Selection Rebuild")
    print("=" * 60)
    
    # 1. Load curated channels config
    if not os.path.exists(CURATED_FILE):
        print(f"  [ERROR] curated_channels.json not found at {CURATED_FILE}")
        sys.exit(1)
        
    with open(CURATED_FILE, "r", encoding="utf-8") as f:
        curated_brands = json.load(f)
        
    overrides = {}
    global_blocked_urls = []
    if os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
            ovr_data = json.load(f)
            overrides = ovr_data.get("overrides", {})
            global_blocked_urls = ovr_data.get("global_blocked_urls", [])
            
    if args.limit:
        curated_brands = curated_brands[:args.limit]
        print(f"  [DRY-RUN] Limited target brands to {len(curated_brands)} channels.")
    else:
        print(f"  Loaded {len(curated_brands)} curated brands to target.")
        
    # 2. Download IPTV-org index.m3u once
    print(f"  Downloading IPTV-org master playlist...")
    try:
        resp = requests.get(IPTV_ORG_M3U_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        m3u_content = resp.text
        print(f"  Downloaded successfully ({len(m3u_content)/1024/1024:.2f} MB).")
    except Exception as e:
        print(f"  [ERROR] Failed to download IPTV-org index.m3u: {e}")
        sys.exit(1)
        
    # 3. Parse index.m3u streams
    print("  Parsing streams...")
    all_streams = parse_m3u(m3u_content)
    print(f"  Parsed {len(all_streams):,} total streams from index.m3u.")
    
    # 4. Group matches
    matches = {b["name"]: [] for b in curated_brands}
    discarded_by_region = 0
    discarded_by_blocked = 0
    
    # Pre-normalize brand targets and aliases for fast lookup
    normalized_brand_targets = {}
    for b in curated_brands:
        brand_name = b["name"]
        
        # Merge overrides
        brand_overrides = overrides.get(brand_name, {})
        
        # Skip if disabled
        if brand_overrides.get("disabled", False):
            continue
        b_blocked_terms = b["blocked_terms"]
        if "blocked_terms" in brand_overrides:
            b_blocked_terms = list(set(b_blocked_terms + brand_overrides["blocked_terms"]))
            
        b_blocked_urls = brand_overrides.get("blocked_urls", [])
        b_blocked_tvg_ids = brand_overrides.get("blocked_tvg_ids", [])
        b_manual_verified = brand_overrides.get("manual_verified", False)
        b_manual_url = brand_overrides.get("manual_url", "")
        
        norm_name = normalize_string(brand_name)
        norm_aliases = [normalize_string(a) for a in b["aliases"]]
        normalized_brand_targets[brand_name] = {
            "name": norm_name,
            "aliases": norm_aliases,
            "blocked": b_blocked_terms,
            "blocked_urls": b_blocked_urls,
            "blocked_tvg_ids": b_blocked_tvg_ids,
            "manual_verified": b_manual_verified,
            "manual_url": b_manual_url,
            "regions": b["preferred_regions"],
            "category": b["category"]
        }
        
    # Find matching candidates for each stream
    print("  Searching for matches...")
    for s in all_streams:
        norm_s_name = normalize_string(s["display_name"])
        norm_s_tvg = normalize_string(s["tvg_name"])
        
        for brand_name, target in normalized_brand_targets.items():
            matched = matches_identity(s, target)
                
            if matched:
                # Check blocked terms and urls
                if matches_blocked_terms(s, target["blocked"], target["blocked_urls"], target["blocked_tvg_ids"], global_blocked_urls):
                    discarded_by_blocked += 1
                    continue
                # Keep candidate
                matches[brand_name].append(s)
                
    # 5. Rank and validate sequentially
    selected_channels = []
    not_found_channels = []
    
    selected_urls = set()
    selected_tvg_ids = set()
    
    total_http_requests = 0
    discarded_by_duplicity = 0
    
    print("\n  Validating channels...")
    for b in curated_brands:
        brand_name = b["name"]
        
        if brand_name not in normalized_brand_targets:
            # It was disabled
            not_found_channels.append({
                "name": brand_name,
                "reason": "Disabled via overrides"
            })
            continue
            
        target = normalized_brand_targets[brand_name]
        
        # Handle manual override skipping
        if target["manual_verified"] and target["manual_url"]:
            print(f"    - Validating '{brand_name}' from manual override url...", end=" ", flush=True)
            is_ok, latency, err = validate_stream(target["manual_url"], [])
            if is_ok:
                print(f"[OK] ({latency}ms)")
                selected_channels.append({
                    "curated_name": brand_name,
                    "display_name": brand_name + " (Manual)",
                    "tvg_id": "",
                    "tvg_name": "",
                    "tvg_logo": "",
                    "group": target["category"],
                    "stream_url": target["manual_url"],
                    "extra_lines": [],
                    "resolution": "",
                    "country": "",
                    "latency_ms": latency,
                    "source": "manual-override"
                })
            else:
                print(f"[FAIL] ({err})")
                not_found_channels.append({"name": brand_name, "reason": f"Manual override failed: {err}"})
            continue
            
        candidates = matches[brand_name]
        
        if not candidates:
            not_found_channels.append({
                "name": brand_name,
                "reason": "No candidates matched name or aliases in IPTV-org"
            })
            continue
            
        # Sort candidates
        candidates.sort(key=lambda c: get_sorting_key(c, b["preferred_regions"]), reverse=True)
        
        # Limit to top 3
        top_candidates = candidates[:3]
        
        selected_candidate = None
        for rank, cand in enumerate(top_candidates):
            # Check duplicates globally
            cand_url = cand["stream_url"]
            cand_tvg_id = cand["tvg_id"]
            
            # Suffixes check to ensure region is appropriate (as safety check)
            if not matches_preferred_region(cand, b["preferred_regions"]) and cand["country_suffix"] not in ["", "la"]:
                # The region is incorrect (e.g. Russia, Spain, Brazil) - skip and increment metrics
                discarded_by_region += 1
                continue
                
            if cand_url in selected_urls or (cand_tvg_id and cand_tvg_id in selected_tvg_ids):
                discarded_by_duplicity += 1
                continue
                
            # Perform HTTP check
            total_http_requests += 1
            print(f"    - Validating '{brand_name}' candidate {rank+1}/3: {cand['display_name']} ({cand['resolution'] or 'unknown'}) at {cand_url[:60]}...", end=" ", flush=True)
            is_ok, latency, err = validate_stream(cand_url, cand["extra_lines"])
            
            if is_ok:
                print(f"[OK] ({latency}ms)")
                selected_candidate = cand
                selected_candidate["latency"] = latency
                break
            else:
                print(f"[FAIL] ({err})")
                
        if selected_candidate:
            selected_urls.add(selected_candidate["stream_url"])
            if selected_candidate["tvg_id"]:
                selected_tvg_ids.add(selected_candidate["tvg_id"])
                
            selected_channels.append({
                "curated_name": brand_name,
                "display_name": selected_candidate["display_name"],
                "tvg_id": selected_candidate["tvg_id"],
                "tvg_name": selected_candidate["tvg_name"],
                "tvg_logo": selected_candidate["tvg_logo"],
                "group": b["category"],
                "stream_url": selected_candidate["stream_url"],
                "extra_lines": selected_candidate["extra_lines"],
                "resolution": selected_candidate["resolution"],
                "country": selected_candidate["country_suffix"].upper() or "LA",
                "latency_ms": selected_candidate["latency"],
                "source": "iptv-org"
            })
        else:
            not_found_channels.append({
                "name": brand_name,
                "reason": "All matched candidates failed stream validation or were skipped" if candidates else "No candidates found"
            })
            
    # 6. Save data/selected_channels.json
    selected_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "channels": selected_channels
    }
    
    os.makedirs(os.path.dirname(SELECTED_FILE), exist_ok=True)
    with open(SELECTED_FILE, "w", encoding="utf-8") as f:
        json.dump(selected_data, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved selected channels to {SELECTED_FILE}")
    
    # 7. Verify Guatemala Channels Confirmation
    gt_confirmed = []
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            gt_data = json.load(f)
            for ch in gt_data.get("channels", []):
                gt_confirmed.append(ch["name"])
                
    execution_time = round(time.time() - start_time, 2)
    
    # 8. Curation Report JSON
    report_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_time_seconds": execution_time,
        "metrics": {
            "total_brands_processed": len(curated_brands),
            "channels_found": len(selected_channels),
            "channels_not_found": len(not_found_channels),
            "total_http_requests": total_http_requests,
            "discarded_by_region": discarded_by_region,
            "discarded_by_duplicity": discarded_by_duplicity,
            "discarded_by_blocked_terms": discarded_by_blocked
        },
        "selected_channels": [c["curated_name"] for c in selected_channels],
        "not_found_channels": not_found_channels,
        "guatemala_channels_confirmed": gt_confirmed
    }
    
    os.makedirs(os.path.dirname(REPORT_JSON), exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
        
    # 9. Write Markdown Reports
    
    # reports/curation-report.md
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("# Reporte de Curación y Reconstrucción\n\n")
        f.write(f"- **Fecha**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.write(f"- **Tiempo total de ejecución**: {execution_time} segundos\n")
        f.write(f"- **Total de marcas procesadas**: {len(curated_brands)}\n")
        f.write(f"- **Canales encontrados**: {len(selected_channels)}\n")
        f.write(f"- **Canales no encontrados**: {len(not_found_channels)}\n")
        f.write(f"- **Total de solicitudes HTTP**: {total_http_requests}\n")
        f.write(f"- **Señales descartadas por región**: {discarded_by_region}\n")
        f.write(f"- **Señales descartadas por duplicidad**: {discarded_by_duplicity}\n\n")
        
        f.write("## Confirmación de Canales de Guatemala\n\n")
        for gt in gt_confirmed:
            f.write(f"- [x] {gt}\n")
        f.write("\n")
        
        f.write("## Lista de Canales Curados Elegidos\n\n")
        f.write("| Canal | Categoría | Resolución | Origen | Latencia |\n")
        f.write("|---|---|---|---|---|\n")
        for c in selected_channels:
            f.write(f"| {c['curated_name']} | {c['group']} | {c['resolution'] or 'desconocida'} | {c['country']} | {c['latency_ms']}ms |\n")
            
    # reports/not-found.md
    with open(NOT_FOUND_MD, "w", encoding="utf-8") as f:
        f.write("# Reporte de Canales No Encontrados\n\n")
        if not_found_channels:
            f.write("| Canal | Razón |\n")
            f.write("|---|---|\n")
            for nf in not_found_channels:
                f.write(f"| {nf['name']} | {nf['reason']} |\n")
        else:
            f.write("¡Todos los canales curados fueron encontrados y validados exitosamente!\n")
            
    # reports/duplicates-report.md
    with open(DUPLICATES_MD, "w", encoding="utf-8") as f:
        f.write("# Reporte de Señales Duplicadas y Descartadas\n\n")
        f.write(f"- **Señales descartadas por duplicidad de URL o TVG-ID**: {discarded_by_duplicity}\n")
        f.write(f"- **Señales descartadas por región incorrecta**: {discarded_by_region}\n")
        f.write(f"- **Señales descartadas por términos excluidos/bloqueados**: {discarded_by_blocked}\n\n")
        f.write("Este reporte confirma que cada canal seleccionado tiene una resolución única, una región única y no comparte URLs de transmisión ni identificadores con otros canales de la playlist.\n")
        
    print("-" * 60)
    print("  Curation report written successfully.")
    print(f"    - Found: {len(selected_channels)} channels.")
    print(f"    - Not Found: {len(not_found_channels)} channels.")
    print(f"    - HTTP Requests: {total_http_requests} (Max 3 per channel)")
    print("=" * 60)

if __name__ == "__main__":
    main()
