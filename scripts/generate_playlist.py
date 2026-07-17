#!/usr/bin/env python3
"""
generate_playlist.py — Playlist generator for IPTV Guatemala.

Combines local Guatemala channels and selected curated channels, cleans display
names, sorts them by group, and generates the final index.m3u playlist.
"""

import os
import sys
import json
import re
from datetime import datetime, timezone

# ─── Paths ───────────────────────────────────────────────────────────
BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CHANNELS_FILE = os.path.join(BASE_DIR, "data", "channels.json")
SELECTED_FILE = os.path.join(BASE_DIR, "data", "selected_channels.json")
REPORT_FILE = os.path.join(BASE_DIR, "reports", "stream-status.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "index.m3u")

# Permitted groups order
GROUP_ORDER = [
    "Guatemala",
    "Películas y Series",
    "Entretenimiento",
    "Noticias",
    "Documentales",
    "Infantil"
]

def clean_display_name(name):
    """
    Cleans names for display according to formatting rules:
    e.g. AXN Latin America (1080p) -> AXN
    """
    n = name
    # Remove resolution tags
    n = re.sub(r'\b(1080[pi]|720p|480p|360p|hd|sd|fhd|uhd|4k)\b', '', n, flags=re.IGNORECASE)
    # Remove region tags
    n = re.sub(r'\b(latin america|latam|latinoamerica|latinoamérica|panregional|mexico|méxico|colombia|argentina|chile|andes)\b', '', n, flags=re.IGNORECASE)
    # Remove parenthesized or bracketed text
    n = re.sub(r'\([^)]*\)', '', n)
    n = re.sub(r'\[[^\]]*\]', '', n)
    # Clean up multiple spaces and strip
    n = re.sub(r'\s+', ' ', n).strip()
    return n

def load_channels():
    """Load local Guatemala channels."""
    if not os.path.exists(CHANNELS_FILE):
        print(f"  [ERROR] {CHANNELS_FILE} not found.")
        sys.exit(1)
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    channels = []
    for ch in data.get("channels", []):
        if ch.get("enabled", True):
            channels.append({
                "id": ch.get("id", ""),
                "name": clean_display_name(ch.get("name", "")),
                "logo": ch.get("logo", ""),
                "group": "Guatemala",
                "stream_url": ch.get("stream_url", ""),
                "extra_lines": ch.get("extra_lines", []),
                "source": "local"
            })
    return channels

def load_selected_channels():
    """Load selected curated channels."""
    if not os.path.exists(SELECTED_FILE):
        print(f"  [INFO] Selected channels file {SELECTED_FILE} not found. Skipping curated channels.")
        return []
    with open(SELECTED_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    channels = []
    for ch in data.get("channels", []):
        # Category/group validation
        group = ch.get("group", "")
        if group not in GROUP_ORDER:
            # Skip or fallback to Entretenimiento
            group = "Entretenimiento"
            
        channels.append({
            "id": ch.get("tvg_id", ""),
            "name": clean_display_name(ch.get("curated_name", ch.get("name", ""))),
            "logo": ch.get("tvg_logo", ""),
            "group": group,
            "stream_url": ch.get("stream_url", ""),
            "extra_lines": ch.get("extra_lines", []),
            "source": "iptv-org"
        })
    return channels

def load_stream_status():
    """Load stream status to filter offline local channels if necessary."""
    if not os.path.exists(REPORT_FILE):
        return {}
    try:
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {ch.get("id"): ch.get("online", False) for ch in data.get("channels", [])}
    except Exception:
        return {}

def sort_channels(channels):
    """Sort by group order, and then alphabetically by name."""
    def sort_key(ch):
        group = ch.get("group", "Entretenimiento")
        try:
            group_idx = GROUP_ORDER.index(group)
        except ValueError:
            group_idx = len(GROUP_ORDER)
        return (group_idx, ch.get("name", "").lower())
    return sorted(channels, key=sort_key)

def generate_m3u(channels):
    """Generate M3U content."""
    lines = ["#EXTM3U", ""]
    for ch in channels:
        extinf = (
            f'#EXTINF:-1 tvg-id="{ch["id"]}" '
            f'tvg-name="{ch["name"]}" '
            f'tvg-logo="{ch["logo"]}" '
            f'group-title="{ch["group"]}"'
            f',{ch["name"]}'
        )
        lines.append(extinf)
        for extra in ch.get("extra_lines", []):
            lines.append(extra)
        lines.append(ch["stream_url"])
        lines.append("")
    return "\n".join(lines)

def main():
    print("=" * 60)
    print("  IPTV Guatemala - Playlist Generator")
    print("=" * 60)
    
    # 1. Load channels
    gt_channels = load_channels()
    curated_channels = load_selected_channels()
    
    # 2. Filter offline local channels if status exists
    status_map = load_stream_status()
    final_gt_channels = []
    for ch in gt_channels:
        ch_id = ch["id"]
        # If we have status and it's marked offline, skip it
        if status_map and ch_id in status_map and not status_map[ch_id]:
            print(f"  [INFO] Skipping offline local channel: {ch['name']}")
            continue
        final_gt_channels.append(ch)
        
    combined = final_gt_channels + curated_channels
    
    # 3. Sort
    sorted_channels = sort_channels(combined)
    
    # 4. Generate & write
    m3u_content = generate_m3u(sorted_channels)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(m3u_content)
        
    print(f"  Generated playlist at {OUTPUT_FILE}")
    print(f"  Total channels: {len(sorted_channels)}")
    print(f"    - Guatemala: {len(final_gt_channels)}")
    print(f"    - Curated: {len(curated_channels)}")
    print("=" * 60)

if __name__ == "__main__":
    main()
