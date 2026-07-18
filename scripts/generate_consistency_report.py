import json
import re

def main():
    # 1. Parse selected_channels.json
    try:
        with open("data/selected_channels.json", "r", encoding="utf-8") as f:
            selected_data = json.load(f)
            json_channels = {ch["curated_name"] for ch in selected_data.get("channels", [])}
    except Exception as e:
        print(f"Error reading selected_channels.json: {e}")
        json_channels = set()

    # 2. Parse final-channel-list.md
    md_channels = set()
    try:
        with open("reports/final-channel-list.md", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("| ") and "Canal" not in line and "---" not in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) > 2:
                        md_channels.add(parts[2])
    except Exception as e:
        print(f"Error reading final-channel-list.md: {e}")

    # 3. Parse index.m3u
    m3u_channels = set()
    m3u_pairs = {}
    try:
        with open("index.m3u", "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith("#EXTINF"):
                    # Extract name after comma
                    name = line.split(",")[-1].strip()
                    # Find URL
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
                    m3u_channels.add(name)
                    m3u_pairs[name] = url
                    i = j
                else:
                    i += 1
    except Exception as e:
        print(f"Error reading index.m3u: {e}")

    # Calculate sets
    all_channels = json_channels | md_channels | m3u_channels
    set_a = json_channels & md_channels & m3u_channels
    set_b = md_channels - m3u_channels
    set_c = m3u_channels - md_channels

    print(f"Total in JSON: {len(json_channels)}")
    print(f"Total in MD: {len(md_channels)}")
    print(f"Total in M3U: {len(m3u_channels)}")
    print(f"Present in all (A): {len(set_a)}")
    print(f"In MD but not M3U (B): {len(set_b)}")
    print(f"In M3U but not MD (C): {len(set_c)}")

    # Generate Report
    report = [
        "# Reporte de Consistencia de Playlist\n",
        "| Canal | selected_channels.json | final-channel-list.md | index.m3u | URL válida | Motivo |",
        "|-------|------------------------|-----------------------|-----------|------------|--------|"
    ]

    for ch in sorted(list(all_channels)):
        in_json = "✅" if ch in json_channels else "❌"
        in_md = "✅" if ch in md_channels else "❌"
        in_m3u = "✅" if ch in m3u_channels else "❌"
        url = m3u_pairs.get(ch, "")
        url_valid = "✅" if url else "❌"
        
        motivo = ""
        if ch in set_b:
            motivo = "Incluido en reporte pero ausente en playlist real"
        elif ch in set_c:
            motivo = "Incluido en playlist pero ausente en reporte"
        elif not url:
            motivo = "Entrada M3U sin URL"
            
        report.append(f"| {ch} | {in_json} | {in_md} | {in_m3u} | {url_valid} | {motivo} |")

    with open("reports/playlist-consistency-report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))
        f.write("\n")

    print("\nReport saved to reports/playlist-consistency-report.md")

if __name__ == "__main__":
    main()
