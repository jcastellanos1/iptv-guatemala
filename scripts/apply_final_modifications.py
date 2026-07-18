#!/usr/bin/env python3
import json
import sys

def main():
    # --- 1. UPDATE OVERRIDES JSON ---
    overrides_file = "data/channel_overrides.json"
    with open(overrides_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    manual_channels = {
        "Cinecanal": {
            "category": "Películas y Series",
            "url": "http://138.186.23.7:8082/CINECANAL/index.m3u8",
            "tvg_id": "CinecanalLatinAmerica.us@Panregional"
        },
        "Telemundo": {
            "category": "Entretenimiento",
            "url": "http://138.121.15.230:9002/TELEMUNDO/index.m3u8",
            "tvg_id": "TelemundoInternacional.us@Panregional"
        },
        "TNT Novelas": {
            "category": "Películas y Series",
            "url": "http://138.186.23.7:8082/TNTNOVELAS/index.m3u8",
            "tvg_id": ""
        },
        "Universal Comedy": {
            "category": "Películas y Series",
            "url": "http://bantel-cdn1.iptvperu.tv:1935/btnscrtn/universalcomedy/playlist.m3u8",
            "tvg_id": ""
        },
        "Canal Latino 1": {
            "category": "Entretenimiento",
            "url": "http://72.1.184.5:8089/play/a05d/index.m3u8",
            "tvg_id": ""
        },
        "Canal Cine Latino 2": {
            "category": "Películas y Series",
            "url": "https://jmp2.uk/plu-69fcaa71ea95ffff0987f555.m3u8",
            "tvg_id": ""
        }
    }

    if "overrides" not in data:
        data["overrides"] = {}

    for name, info in manual_channels.items():
        data["overrides"][name] = {
            "manual_verified": True,
            "status": "CONFIRMADO_MANUAL",
            "source": "user_supplied",
            "locked": True,
            "manual_url": info["url"]
        }
        if info["tvg_id"]:
            data["overrides"][name]["selected_tvg_id"] = info["tvg_id"]

    with open(overrides_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # --- 2. PARSE EXISTING index.m3u ---
    m3u_file = "index.m3u"
    try:
        with open(m3u_file, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception as e:
        print(f"Error reading index.m3u: {e}")
        return

    channels = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            extinf = line
            # Extract name and tvg-id and group-title
            name = line.split(",")[-1].strip()
            
            tid = ""
            if 'tvg-id="' in line:
                tid = line.split('tvg-id="')[1].split('"')[0]
                
            group = ""
            if 'group-title="' in line:
                group = line.split('group-title="')[1].split('"')[0]

            j = i + 1
            url = ""
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith("#"):
                    url = nxt
                    break
                elif nxt.startswith("#EXTINF"):
                    break
                j += 1
            if url:
                channels.append({
                    "name": name,
                    "url": url,
                    "tvg_id": tid,
                    "group": group,
                    "extinf": extinf,
                    "origen": "CONFIRMADO" if "CONFIRMADO" in extinf or "Guatemala" in group else "AUTO_FINAL"
                })
            i = j
        else:
            i += 1

    # --- 3. FILTER CHANNELS ---
    filtered_channels = []
    for ch in channels:
        n_low = ch["name"].lower()
        t_low = ch["tvg_id"].lower()
        u_low = ch["url"].lower()
        
        # Check Pluto TV
        is_pluto = "pluto" in n_low or "pluto" in t_low or "pluto" in u_low
        if is_pluto:
            if ch["url"] != "https://jmp2.uk/plu-69fcaa71ea95ffff0987f555.m3u8":
                continue # eliminate
                
        # Check Discovery
        if "discovery" in n_low:
            continue # eliminate
            
        filtered_channels.append(ch)

    # Convert to dict for fast deduplication
    final_dict = {}
    for ch in filtered_channels:
        final_dict[ch["url"]] = ch

    # --- 4. ADD MANUAL CHANNELS ---
    for name, info in manual_channels.items():
        # Remove any existing by URL to replace
        if info["url"] in final_dict:
            del final_dict[info["url"]]
            
        final_dict[info["url"]] = {
            "name": name,
            "url": info["url"],
            "tvg_id": info["tvg_id"],
            "group": info["category"],
            "origen": "MANUAL_USUARIO"
        }

    # Format the final list
    final_list = list(final_dict.values())

    # --- 5. WRITE NEW M3U ---
    m3u_lines = ["#EXTM3U", ""]
    for ch in final_list:
        tid = ch["tvg_id"]
        grp = ch["group"]
        nm = ch["name"]
        
        # User requested exact format:
        # #EXTINF:-1 tvg-id="..." group-title="Categoría",Nombre
        # URL
        
        m3u_lines.append(f'#EXTINF:-1 tvg-id="{tid}" group-title="{grp}",{nm}')
        m3u_lines.append(ch["url"])
    
    with open(m3u_file, "wb") as f:
        # Write exactly with LF (\n)
        content = "\n".join(m3u_lines) + "\n"
        f.write(content.encode("utf-8"))

    # --- 6. VALIDATION ---
    names = [ch["name"] for ch in final_list]
    for man in manual_channels.keys():
        cnt = names.count(man)
        if cnt != 1:
            print(f"VALIDATION ERROR: {man} appears {cnt} times")

    urls = [ch["url"] for ch in final_list]
    if len(urls) != len(set(urls)):
        print("VALIDATION ERROR: Duplicate URLs found")
        
    tids = [ch["tvg_id"] for ch in final_list if ch["tvg_id"]]
    if len(tids) != len(set(tids)):
        print("VALIDATION ERROR: Duplicate TVG-IDs found")
        
    for ch in final_list:
        n_low = ch["name"].lower()
        if "discovery" in n_low:
            print(f"VALIDATION ERROR: Found Discovery channel: {ch['name']}")
        if "pluto" in n_low and ch["url"] != "https://jmp2.uk/plu-69fcaa71ea95ffff0987f555.m3u8":
            print(f"VALIDATION ERROR: Found Pluto TV channel: {ch['name']}")

    print(f"Total valid pairs: {len(final_list)}")

    # --- 7. WRITE MARKDOWN REPORT ---
    md_file = "reports/final-channel-list.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("# Lista Definitiva de Canales\n\n")
        f.write("| N.º | Canal | Categoría | TVG-ID | Origen |\n")
        f.write("|-----|-------|-----------|--------|--------|\n")
        for i, ch in enumerate(final_list, 1):
            f.write(f"| {i:02d} | {ch['name']} | {ch['group']} | {ch['tvg_id'] if ch['tvg_id'] else '-'} | {ch['origen']} |\n")
            
    print("Modifications applied successfully.")

if __name__ == "__main__":
    main()
