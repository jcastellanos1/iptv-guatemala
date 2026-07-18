import os
import json

BASE_DIR = os.path.normpath(os.path.dirname(os.path.dirname(__file__)))
SELECTED_FILE = os.path.join(BASE_DIR, "data", "selected_channels.json")
OVERRIDES_FILE = os.path.join(BASE_DIR, "data", "channel_overrides.json")
REPORT_MD = os.path.join(BASE_DIR, "reports", "manual-review-lote2.md")
REVIEW_M3U = os.path.join(BASE_DIR, "reports", "review-playlist-lote2.m3u")

def main():
    if not os.path.exists(SELECTED_FILE):
        print(f"File not found: {SELECTED_FILE}")
        return

    with open(SELECTED_FILE, "r", encoding="utf-8") as f:
        sel_data = json.load(f)

    with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
        ovr_data = json.load(f)

    overrides = ovr_data.get("overrides", {})
    
    channels = sel_data.get("channels", [])
    
    filtered_channels = []
    
    # Track duplicates
    seen_urls = set()
    seen_tvg_ids = set()
    seen_names = set()
    
    duplicates = []
    
    for ch in channels:
        req_name = ch.get("curated_name", "")
        sel_name = ch.get("display_name", "")
        tvg_id = ch.get("tvg_id", "")
        res = ch.get("resolution", "")
        country = ch.get("country", "")
        url = ch.get("stream_url", "")
        
        # Exclude confirmed channels
        if overrides.get(req_name, {}).get("manual_verified", False):
            continue
            
        # Exclude specific explicit ones just in case
        if req_name in ["History 2", "NTN24", "Milenio Televisión", "Foro TV"]:
            continue
            
        if "bantel-cdn1.iptvperu.tv" in url:
            continue
            
        if not url:
            continue
            
        # Duplicates check
        is_dup = False
        if url in seen_urls:
            duplicates.append(f"{req_name} (Duplicate URL: {url})")
            is_dup = True
        if tvg_id and tvg_id in seen_tvg_ids:
            duplicates.append(f"{req_name} (Duplicate TVG-ID: {tvg_id})")
            is_dup = True
        if req_name.lower() in seen_names:
            duplicates.append(f"{req_name} (Duplicate Base Name)")
            is_dup = True
            
        if is_dup:
            continue
            
        seen_urls.add(url)
        if tvg_id:
            seen_tvg_ids.add(tvg_id)
        seen_names.add(req_name.lower())
        
        filtered_channels.append(ch)

    if len(filtered_channels) != 19:
        print(f"Warning: Expected 19 channels, found {len(filtered_channels)}")
        if duplicates:
            print(f"Duplicates found: {duplicates}")

    # For numbering
    counter = 1
    
    m3u_lines = ["#EXTM3U\n"]
    md_lines = [
        "| N.º | Canal solicitado | Señal seleccionada | TVG-ID | Resolución | País/Región | URL | Estado |",
        "|-----|------------------|--------------------|--------|------------|-------------|-----|--------|"
    ]
    
    print("--- CHANNEL LIST ---")
    for ch in filtered_channels:
        req_name = ch.get("curated_name", "")
        sel_name = ch.get("display_name", "")
        tvg_id = ch.get("tvg_id", "")
        res = ch.get("resolution", "")
        country = ch.get("country", "")
        url = ch.get("stream_url", "")
        
        num_str = f"{counter:02d}"
        
        # Write to Markdown
        md_lines.append(f"| {num_str} | {req_name} | {sel_name} | {tvg_id} | {res} | {country} | {url} | **DUDOSO** |")
        
        # Write to M3U
        m3u_lines.append(f"#EXTINF:-1 tvg-id=\"{tvg_id}\" tvg-name=\"{req_name}\" group-title=\"{ch.get('group', 'Revision')}\",{num_str} - {req_name}\n")
        m3u_lines.append(f"{url}\n")
        
        print(f"{num_str} - {req_name}")
        counter += 1

    os.makedirs(os.path.dirname(REPORT_MD), exist_ok=True)
    
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")
        
    with open(REVIEW_M3U, "w", encoding="utf-8", newline='\n') as f:
        f.writelines(m3u_lines)
        
    print(f"Duplicates: {len(duplicates)}")
    print(f"Total Written: {len(filtered_channels)}")

if __name__ == "__main__":
    main()
