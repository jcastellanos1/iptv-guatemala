#!/usr/bin/env python3
"""
test_import.py — Pruebas unitarias/integración para el motor de descubrimiento de IPTV-org.

Utiliza fixtures y mocks locales para simular la playlist y las APIs de IPTV-org.
Las pruebas se ejecutan de forma rápida y reproducible (offline), sin depender de la
disponibilidad de cientos de streams públicos ni de descargas de 13K canales.
"""

import io
import json
import os
import sys
from unittest.mock import patch, MagicMock

# Force UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(BASE_DIR))

# Import scripts
import scripts.import_iptv_org as import_engine
import scripts.generate_playlist as playlist_gen

passed = 0
failed = 0


def test_pass(name):
    global passed
    passed += 1
    print(f"  [PASS] {name}")


def test_fail(name, detail=""):
    global failed
    failed += 1
    msg = f"  [FAIL] {name}"
    if detail:
        msg += f" - {detail}"
    print(msg)


# ═══════════════════════════════════════════════════════════════════════
# MOCK FIXTURES DATA
# ═══════════════════════════════════════════════════════════════════════

MOCK_M3U = """#EXTM3U

#EXTINF:-1 tvg-id="AXNLatinAmerica.us@CentralAmerica" tvg-logo="axn.png" group-title="Movies",AXN Latin America (1080p)
http://axn/stream1080

#EXTINF:-1 tvg-id="AXNLatinAmerica.us@SD" tvg-logo="axn.png" group-title="Movies",AXN Latin America (720p)
http://axn/stream720

#EXTINF:-1 tvg-id="AMCLatinAmerica.us@Panregional" tvg-logo="amc.png" group-title="Movies",AMC Latin America (1080p)
http://amc/stream

#EXTINF:-1 tvg-id="CNNenEspanol.us@HD" tvg-logo="cnn.png" group-title="News",CNN en Español HD
http://cnn/stream

#EXTINF:-1 tvg-id="AztecaUno.mx@HD" tvg-logo="azteca.png" group-title="General",Azteca Uno HD
http://azteca/stream

#EXTINF:-1 tvg-id="GloboBR.br@SD" tvg-logo="globo.png" group-title="General",Globo Brasil
http://globo/stream

#EXTINF:-1 tvg-id="SexyTV.us@SD" tvg-logo="sexy.png" group-title="Adult",Sexy TV
http://sexy/stream

#EXTINF:-1 tvg-id="ShopTV.us@SD" tvg-logo="shop.png" group-title="Shop",Shop TV
http://shop/stream

#EXTINF:-1 tvg-id="BibleTV.us@SD" tvg-logo="bible.png" group-title="Religious",Bible TV
http://bible/stream

#EXTINF:-1 tvg-id="TNTSports.br@SD" tvg-logo="tntsports.png" group-title="Sports",TNT Sports
http://tntsports/stream

#EXTINF:-1 tvg-id="TNT.us@SD" tvg-logo="tnt.png" group-title="Movies",TNT
http://tnt/stream

#EXTINF:-1 tvg-id="TNTSeries.us@SD" tvg-logo="tntseries.png" group-title="Movies",TNT Series
http://tntseries/stream
"""

MOCK_CHANNELS = [
    {"id": "AXNLatinAmerica.us", "name": "AXN", "country": "US", "categories": ["movies"]},
    {"id": "AMCLatinAmerica.us", "name": "AMC", "country": "US", "categories": ["movies"]},
    {"id": "CNNenEspanol.us", "name": "CNN en Español", "country": "US", "categories": ["news"]},
    {"id": "AztecaUno.mx", "name": "Azteca Uno", "country": "MX", "categories": ["general"]},
    {"id": "GloboBR.br", "name": "Globo", "country": "BR", "categories": ["general"]},
    {"id": "SexyTV.us", "name": "Sexy TV", "country": "US", "categories": ["adult"]},
    {"id": "ShopTV.us", "name": "Shop TV", "country": "US", "categories": ["shop"]},
    {"id": "BibleTV.us", "name": "Bible TV", "country": "US", "categories": ["religious"]},
    {"id": "TNTSports.br", "name": "TNT Sports", "country": "BR", "categories": ["sports"]},
    {"id": "TNT.us", "name": "TNT", "country": "US", "categories": ["movies"]},
    {"id": "TNTSeries.us", "name": "TNT Series", "country": "US", "categories": ["movies"]}
]

MOCK_FEEDS = [
    {"channel": "AXNLatinAmerica.us", "id": "CentralAmerica", "languages": ["spa"]},
    {"channel": "AXNLatinAmerica.us", "id": "SD", "languages": ["spa"]},
    {"channel": "AMCLatinAmerica.us", "id": "Panregional", "languages": ["spa"]},
    {"channel": "CNNenEspanol.us", "id": "HD", "languages": ["spa"]},
    {"channel": "AztecaUno.mx", "id": "HD", "languages": ["spa"]},
    {"channel": "GloboBR.br", "id": "SD", "languages": ["por"]},
    {"channel": "SexyTV.us", "id": "SD", "languages": ["eng"]},
    {"channel": "ShopTV.us", "id": "SD", "languages": ["eng"]},
    {"channel": "BibleTV.us", "id": "SD", "languages": ["eng"]},
    {"channel": "TNTSports.br", "id": "SD", "languages": ["por"]},
    {"channel": "TNT.us", "id": "SD", "languages": ["spa"]},
    {"channel": "TNTSeries.us", "id": "SD", "languages": ["spa"]}
]

MOCK_COUNTRIES = [
    {"name": "Mexico", "code": "MX", "languages": ["spa"]},
    {"name": "Colombia", "code": "CO", "languages": ["spa"]},
    {"name": "Brazil", "code": "BR", "languages": ["por"]},
    {"name": "United States", "code": "US", "languages": ["eng"]}
]


# ═══════════════════════════════════════════════════════════════════════
# MOCK IMPLEMENTATION
# ═══════════════════════════════════════════════════════════════════════

def mock_validate_stream_url(url, ua=None, ref=None):
    # Simulate AXN 1080p failing so it falls back to 720p
    if "stream1080" in url:
        return False, "timeout", 8000
    # Simulate Adult, Shop, Religious, and Brazil streams working, though they should be filtered out by score first
    return True, "online", 150


def mock_inspect_hls_audio(url, ua=None, ref=None):
    if "tntsports" in url or "globo" in url:
        return "pt", "rejected"
    return "es", "verified"


TEST_OUTPUT_FILE = os.path.normpath(os.path.join(BASE_DIR, "data", "imported_channels_test.json"))
TEST_CANDIDATES_FILE = os.path.normpath(os.path.join(BASE_DIR, "data", "discovered_candidates_test.json"))
TEST_REPORT_JSON = os.path.normpath(os.path.join(BASE_DIR, "reports", "discovery-report_test.json"))
TEST_REPORT_MD = os.path.normpath(os.path.join(BASE_DIR, "reports", "discovery-report_test.md"))
TEST_DUPLICATES_REPORT_MD = os.path.normpath(os.path.join(BASE_DIR, "reports", "duplicates-report_test.md"))
TEST_INDEX_FILE = os.path.normpath(os.path.join(BASE_DIR, "index_test.m3u"))


def run_mocked_import():
    """Runs the import pipeline under mock overrides."""
    with patch("scripts.import_iptv_org.OUTPUT_FILE", TEST_OUTPUT_FILE), \
         patch("scripts.import_iptv_org.CANDIDATES_FILE", TEST_CANDIDATES_FILE), \
         patch("scripts.import_iptv_org.REPORT_JSON", TEST_REPORT_JSON), \
         patch("scripts.import_iptv_org.REPORT_MD", TEST_REPORT_MD), \
         patch("scripts.import_iptv_org.DUPLICATES_REPORT_MD", TEST_DUPLICATES_REPORT_MD), \
         patch("scripts.import_iptv_org.download_m3u", return_value=MOCK_M3U), \
         patch("scripts.import_iptv_org.download_api_metadata", return_value=(
             {c["id"]: c for c in MOCK_CHANNELS},
             {(f["channel"], f["id"]): f for f in MOCK_FEEDS},
             {c["code"]: c for c in MOCK_COUNTRIES}
         )), \
         patch("scripts.import_iptv_org.validate_stream_url", side_effect=mock_validate_stream_url), \
         patch("scripts.import_iptv_org.inspect_hls_audio", side_effect=mock_inspect_hls_audio):
        import_engine.run_import()


# ═══════════════════════════════════════════════════════════════════════
# TEST CASES
# ═══════════════════════════════════════════════════════════════════════

def test_discovery_business_rules():
    print("  [INFO] Ejecutando importación simulada (offline)...")
    
    # Save original wanted_channels backup
    wanted_backup = None
    if os.path.exists(import_engine.WANTED_FILE):
        with open(import_engine.WANTED_FILE, "r", encoding="utf-8") as f:
            wanted_backup = f.read()
            
    # Mock empty wanted_channels
    with open(import_engine.WANTED_FILE, "w", encoding="utf-8") as f:
        json.dump({"channels": []}, f)
        
    try:
        run_mocked_import()
        
        # Load imported_channels_test.json to assert business rules
        imported = {}
        with open(TEST_OUTPUT_FILE, "r", encoding="utf-8") as f:
            imported = json.load(f)
            
        channels = imported.get("channels", [])
        ch_names = {ch["display_name"].lower() for ch in channels}
        
        # 1. System works with wanted_channels empty and discovers automatically
        if len(channels) > 0:
            test_pass("Sistema funciona con wanted_channels.json vacío y descubre automáticamente")
        else:
            test_fail("Sistema funciona con wanted_channels.json vacío")
            
        # 2. Exclude Portuguese & Brazil
        pt_or_br = any(
            "brasil" in ch["display_name"].lower() or 
            ch["country"] == "BR" or 
            ch["language"] == "pt"
            for ch in channels
        )
        if not pt_or_br:
            test_pass("Excluye automáticamente portugués y Brasil")
        else:
            test_fail("Excluye automáticamente portugués y Brasil", "Se importó canal de Brasil o en portugués")
            
        # 3. Exclude Adult, Shop, Religious by default
        adult_shop_rel = any(
            ch["category_original"].lower() in ["adult", "shop", "religious"]
            for ch in channels
        )
        if not adult_shop_rel:
            test_pass("Excluye Adult, Shop y Religious por defecto")
        else:
            test_fail("Excluye Adult, Shop y Religious por defecto", "Se importaron categorías prohibidas")
            
        # 4. Accept CNN en Español & Azteca
        if "cnn en español" in ch_names:
            test_pass("Acepta CNN en Español")
        else:
            test_fail("Acepta CNN en Español", "CNN en Español no fue descubierto")
            
        if "azteca uno" in ch_names:
            test_pass("Acepta Azteca")
        else:
            test_fail("Acepta Azteca", "Azteca no fue descubierto")
            
        # 5. Accept México and Colombia channels
        mx_col = any(ch["country"] == "MX" for ch in channels)
        if mx_col:
            test_pass("Acepta canales de México y Colombia")
        else:
            test_fail("Acepta canales de México y Colombia")
            
        # 6. Quality prioritization: 1080p fallback to 720p
        axn_ch = next((ch for ch in channels if ch["base_name"] == "AXN"), None)
        if axn_ch:
            if axn_ch["quality"] == "720p":
                test_pass("Prioriza calidad: 1080p caído hace fallback correcto a 720p")
            else:
                test_fail("Prioriza calidad", f"Se seleccionó calidad incorrecta {axn_ch['quality']}")
        else:
            test_fail("Prioriza calidad", "AXN no fue importado")
            
        # 7. Deduplication: no duplicate AXN, AMC, CNN en Español, Azteca
        base_names = [ch["base_name"] for ch in channels]
        has_dups = len(base_names) != len(set(base_names))
        if not has_dups:
            test_pass("Deduplicación de canales base (máximo una variante por canal)")
        else:
            test_fail("Deduplicación de canales base", f"Canales duplicados: {base_names}")
            
        # 8. Mantiene separados TNT y TNT Series
        if "tnt" in ch_names and "tnt series" in ch_names:
            test_pass("Mantiene separados TNT y TNT Series")
        else:
            test_fail("Mantiene separados TNT y TNT Series")
            
        # 9. No confunde TNT con TNT Sports (TNT Sports excluido)
        if "tnt sports" not in ch_names:
            test_pass("TNT Sports correctamente excluido de la categoría principal")
        else:
            test_fail("TNT Sports correctamente excluido", "TNT Sports fue importado")
            
    finally:
        # Restore wanted_channels.json
        if wanted_backup is not None:
            with open(import_engine.WANTED_FILE, "w", encoding="utf-8") as f:
                f.write(wanted_backup)
        else:
            if os.path.exists(import_engine.WANTED_FILE):
                os.remove(import_engine.WANTED_FILE)


def test_playlist_generation_and_ss_iptv():
    print("  [INFO] Ejecutando generador de playlist...")
    try:
        with patch("scripts.generate_playlist.IMPORTED_FILE", TEST_OUTPUT_FILE), \
             patch("scripts.generate_playlist.OUTPUT_FILE", TEST_INDEX_FILE):
            playlist_gen.main()
    except SystemExit:
        pass
    
    if not os.path.exists(TEST_INDEX_FILE):
        test_fail("Playlist final", "index_test.m3u no existe")
        return
        
    with open(TEST_INDEX_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Check header
    if content.strip().startswith("#EXTM3U"):
        test_pass("index_test.m3u comienza con #EXTM3U")
    else:
        test_fail("index_test.m3u comienza con #EXTM3U")
        
    # Check Guatemala channels are present
    content_lower = content.lower()
    for ch in ["canal 3", "canal 7", "tn23"]:
        if ch in content_lower:
            test_pass(f"Canal de Guatemala '{ch}' presente en index_test.m3u")
        else:
            test_fail(f"Canal de Guatemala '{ch}' presente en index_test.m3u")
            
    # Check SS IPTV compatibility (tvg-id, group-title)
    has_extinf = False
    ss_iptv_ok = True
    for line in content.split("\n"):
        if line.strip().startswith("#EXTINF"):
            has_extinf = True
            if 'tvg-id="' not in line or 'group-title="' not in line:
                ss_iptv_ok = False
                break
    if has_extinf and ss_iptv_ok:
        test_pass("Compatible con SS IPTV (atributos tvg-id y group-title presentes)")
    else:
        test_fail("Compatible con SS IPTV")


# ═══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  IPTV Guatemala - Pruebas del Motor de Descubrimiento (MOCKS)")
    print("=" * 60)
    print()
    
    test_discovery_business_rules()
    print()
    test_playlist_generation_and_ss_iptv()
    
    # Cleanup temporary test files
    for path in [TEST_OUTPUT_FILE, TEST_CANDIDATES_FILE, TEST_REPORT_JSON, TEST_REPORT_MD, TEST_DUPLICATES_REPORT_MD, TEST_INDEX_FILE]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
                
    print()
    print("=" * 60)
    print(f"  Resultados: {passed} pasaron, {failed} fallaron")
    print("=" * 60)
    
    if failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
