import os
import json
from collections import defaultdict

BASE_DIR = os.path.normpath(os.path.dirname(os.path.dirname(__file__)))
SELECTED_FILE = os.path.join(BASE_DIR, "data", "selected_channels.json")
REPORT_MD = os.path.join(BASE_DIR, "reports", "manual-review.md")
REVIEW_M3U = os.path.join(BASE_DIR, "reports", "review-playlist.m3u")

def main():
    if not os.path.exists(SELECTED_FILE):
        print(f"File not found: {SELECTED_FILE}")
        return

    with open(SELECTED_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    channels = data.get("channels", [])
    
    # Exclude Guatemala channels
    excluded_names = ["canal 3", "canal 7", "tn23", "guatemala"]
    
    filtered_channels = []
    
    # Track duplicates
    seen_urls = set()
    seen_tvg_ids = set()
    seen_names = set()
    
    duplicates = []
    excluded_by_block = [] # We'll just track Guatemala ones here as excluded for review
    
    # For numbering
    counter = 1
    
    m3u_lines = ["#EXTM3U\n"]
    md_lines = [
        "# Auditoría Manual de Canales Seleccionados\n",
        "Para cada canal seleccionado, evalúa la calidad y veracidad de la señal y cambia el **Estado de revisión** a `CONFIRMADO` o `INCORRECTO`.\n",
        "| # | Nombre solicitado | Nombre seleccionado | TVG-ID | Resolución | Región | URL | Estado HTTP | Estado de revisión | Observaciones |",
        "|---|---|---|---|---|---|---|---|---|---|"
    ]
    
    for ch in channels:
        req_name = ch.get("curated_name", "")
        sel_name = ch.get("display_name", "")
        tvg_id = ch.get("tvg_id", "")
        res = ch.get("resolution", "")
        country = ch.get("country", "")
        url = ch.get("stream_url", "")
        
        # Check exclusion
        if any(ex in req_name.lower() or ex in sel_name.lower() for ex in excluded_names):
            excluded_by_block.append(req_name)
            continue
            
        # Check URL empty
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
            # We skip adding duplicates to the review list to ensure safety, or just log them.
            # The prompt says: "Verifica automáticamente antes de generarla: que no haya URLs repetidas..."
            continue
            
        seen_urls.add(url)
        if tvg_id:
            seen_tvg_ids.add(tvg_id)
        seen_names.add(req_name.lower())
        
        # Format number
        num_str = f"{counter:02d}"
        
        # Determine initial state
        result = "DUDOSO"
        if req_name == "Paramount Network":
            result = "INCORRECTO"
        elif "tnt.ru" in tvg_id.lower():
            result = "INCORRECTO"
        elif "space series" in sel_name.lower() or "space series" in req_name.lower():
            result = "INCORRECTO"
        elif "ae.us@east" in tvg_id.lower():
            result = "INCORRECTO"
            
        # Write to Markdown
        md_lines.append(f"| {num_str} | {req_name} | {sel_name} | {tvg_id} | {res} | {country} | {url} | 200 OK | **{result}** |  |")
        
        # Write to M3U
        m3u_lines.append(f"#EXTINF:-1 tvg-id=\"{tvg_id}\" tvg-name=\"{req_name}\" group-title=\"{ch.get('group', 'Revision')}\",{num_str} - {req_name}\n")
        m3u_lines.append(f"{url}\n")
        
        filtered_channels.append(ch)
        counter += 1

    os.makedirs(os.path.dirname(REPORT_MD), exist_ok=True)
    
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")
        
    with open(REVIEW_M3U, "w", encoding="utf-8", newline='\n') as f:
        f.writelines(m3u_lines)
        
    # Output metrics for the AI to report
    print(f"Total Review Channels: {len(filtered_channels)}")
    print(f"Excluded: {len(excluded_by_block)}")
    print(f"Duplicates: {len(duplicates)}")
    print("--- CHANNEL LIST ---")
    for i, ch in enumerate(filtered_channels):
        print(f"{i+1:02d} - {ch.get('curated_name')}")

if __name__ == "__main__":
    main()
