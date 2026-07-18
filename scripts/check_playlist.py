#!/usr/bin/env python3
import sys
import collections

def check_playlist(filepath):
    try:
        with open(filepath, "rb") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return False
        
    lines = content.decode('utf-8').splitlines()

    if not lines or lines[0].strip() != "#EXTM3U":
        print("ERROR: Header is not #EXTM3U")
        return False

    extinf_count = 0
    url_count = 0
    valid_pairs = 0
    empty_urls = 0
    malformed = 0

    urls = []
    tvg_ids = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            extinf_count += 1
            
            # Check for tvg-id
            if 'tvg-id="' in line:
                tid = line.split('tvg-id="')[1].split('"')[0]
                if tid:
                    tvg_ids.append(tid)

            # Look for the immediate URL
            url = None
            j = i + 1
            # User specifies: "inmediatamente después una URL", no extra lines pegadas
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt:
                    pass # skip empty
                elif not nxt.startswith("#"):
                    url = nxt
                    break
                elif nxt.startswith("#EXTINF"):
                    # Missing URL for previous EXTINF
                    break
                j += 1
            
            if url:
                url_count += 1
                valid_pairs += 1
                urls.append(url)
            else:
                empty_urls += 1
                malformed += 1
            i = j
        else:
            i += 1

    dup_urls = len(urls) - len(set(urls))
    
    # Exclude empty tvg-ids from duplicates check
    valid_tvg = [t for t in tvg_ids if t]
    dup_tvg = len(valid_tvg) - len(set(valid_tvg))

    print(f"EXTINF entries: {extinf_count}")
    print(f"URL entries: {url_count}")
    print(f"Valid channel pairs: {valid_pairs}")
    print(f"Duplicate URLs: {dup_urls}")
    print(f"Duplicate TVG-IDs: {dup_tvg}")
    print(f"Malformed entries: {malformed}")

    if extinf_count != 75 or valid_pairs != 75 or dup_urls > 0 or dup_tvg > 0 or malformed > 0 or empty_urls > 0:
        print("Final result: FAIL")
        return False
        
    print("Final result: PASS")
    return True

if __name__ == "__main__":
    if not check_playlist("index.m3u"):
        sys.exit(1)
    sys.exit(0)
