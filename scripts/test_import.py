#!/usr/bin/env python3
"""
test_import.py — Pruebas automatizadas para la importación de canales IPTV-org.

Verifica:
1. Validez de todos los archivos JSON
2. Presencia de Canal 3, Canal 7, TN23
3. Exclusión de Brasil, Asia, Europa no hispana
4. Prioridad de AXN Latin America sobre AXN Argentina
5. TNT ≠ TNT Sports
6. Sin duplicados
7. Una sola calidad por canal
8. Atributos M3U bien formados
9. User-Agent y group-title no dentro del título
10. index.m3u comienza con #EXTM3U
11. Compatibilidad con SS IPTV

Uso:
    python scripts/test_import.py
"""

import io
import json
import os
import re
import sys

# Force UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CHANNELS_FILE = os.path.join(BASE_DIR, "data", "channels.json")
IMPORTED_FILE = os.path.join(BASE_DIR, "data", "imported_channels.json")
WANTED_FILE = os.path.join(BASE_DIR, "data", "wanted_channels.json")
OVERRIDES_FILE = os.path.join(BASE_DIR, "data", "channel_overrides.json")
INDEX_FILE = os.path.join(BASE_DIR, "index.m3u")
REPORT_JSON = os.path.join(BASE_DIR, "reports", "import-report.json")

passed = 0
failed = 0
warnings = 0


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


def test_warn(name, detail=""):
    global warnings
    warnings += 1
    msg = f"  [WARN] {name}"
    if detail:
        msg += f" - {detail}"
    print(msg)


def load_json_safe(path):
    """Load JSON file, return None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return None


# ═══════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_json_validity():
    """Test 1: All JSON files are valid."""
    json_files = [CHANNELS_FILE, IMPORTED_FILE, WANTED_FILE, OVERRIDES_FILE, REPORT_JSON]
    for path in json_files:
        basename = os.path.basename(path)
        if not os.path.exists(path):
            test_warn(f"JSON válido: {basename}", "archivo no encontrado")
            continue
        data = load_json_safe(path)
        if data is not None:
            test_pass(f"JSON válido: {basename}")
        else:
            test_fail(f"JSON válido: {basename}", "JSON inválido o error de lectura")


def test_guatemala_channels_present():
    """Test 2: Canal 3, Canal 7, TN23 present in channels.json."""
    data = load_json_safe(CHANNELS_FILE)
    if not data:
        test_fail("Canales guatemaltecos presentes", "No se pudo cargar channels.json")
        return

    channels = data.get("channels", [])
    names = [ch.get("name", "").lower() for ch in channels]
    ids = [ch.get("id", "").lower() for ch in channels]

    required = {
        "Canal 3": ("canal 3", "canal3.gt"),
        "Canal 7": ("canal 7", "canal7.gt"),
        "TN23": ("tn23", "tn23.gt"),
    }

    for label, (name_fragment, id_fragment) in required.items():
        found = any(name_fragment in n for n in names) or any(id_fragment in i for i in ids)
        if found:
            test_pass(f"Canal guatemalteco presente: {label}")
        else:
            test_fail(f"Canal guatemalteco presente: {label}")


def test_brazil_excluded():
    """Test 3: Brazil excluded from imported channels."""
    data = load_json_safe(IMPORTED_FILE)
    if not data:
        test_warn("Brasil excluido", "No se encontró imported_channels.json")
        return

    for ch in data.get("channels", []):
        name = ch.get("selected_name", "").lower()
        region = ch.get("region", "").lower()
        if "brazil" in name or "brasil" in name or "brazil" in region or "brasil" in region:
            test_fail("Brasil excluido", f"Canal con Brasil encontrado: {ch.get('selected_name')}")
            return

    test_pass("Brasil excluido de canales importados")


def test_asia_europe_excluded():
    """Test 3b: Asia and non-Hispanic Europe excluded."""
    data = load_json_safe(IMPORTED_FILE)
    if not data:
        test_warn("Asia/Europa excluidos", "No se encontró imported_channels.json")
        return

    excluded_terms = ["asia", "indonesia", "india", "romania", "bulgaria",
                      "czech", "poland", "hungary", "adriatic", "cee", "balkans"]

    for ch in data.get("channels", []):
        name = ch.get("selected_name", "").lower()
        for term in excluded_terms:
            if term in name:
                test_fail("Asia/Europa excluidos", f"Término '{term}' en: {ch.get('selected_name')}")
                return

    test_pass("Asia y Europa no hispana excluidos")


def test_axn_priority():
    """Test 4: AXN Latin America preferred over AXN Argentina."""
    data = load_json_safe(IMPORTED_FILE)
    if not data:
        test_warn("Prioridad AXN", "No se encontró imported_channels.json")
        return

    for ch in data.get("channels", []):
        if ch.get("query") == "AXN":
            name = ch.get("selected_name", "").lower()
            region = ch.get("region", "").lower()
            if "argentina" in name and "latin" not in name:
                test_fail("Prioridad AXN",
                          f"Se seleccionó AXN Argentina en vez de Latin America: {ch.get('selected_name')}")
            else:
                test_pass(f"Prioridad AXN: {ch.get('selected_name')} (región: {ch.get('region')})")
            return

    test_warn("Prioridad AXN", "No se encontró AXN en canales importados")


def test_tnt_not_sports():
    """Test 5: TNT != TNT Sports."""
    data = load_json_safe(IMPORTED_FILE)
    if not data:
        test_warn("TNT != Sports", "No se encontró imported_channels.json")
        return

    for ch in data.get("channels", []):
        if ch.get("query") == "TNT":
            name = ch.get("selected_name", "").lower()
            if "sports" in name or "sport" in name:
                test_fail("TNT != Sports", f"Se seleccionó TNT Sports: {ch.get('selected_name')}")
            else:
                test_pass(f"TNT != Sports: {ch.get('selected_name')}")
            return

    test_warn("TNT != Sports", "No se encontró TNT en canales importados")


def test_no_duplicates():
    """Test 6: No duplicate channels."""
    data = load_json_safe(IMPORTED_FILE)
    if not data:
        test_warn("Sin duplicados", "No se encontró imported_channels.json")
        return

    urls = []
    queries = []
    for ch in data.get("channels", []):
        url = ch.get("stream_url", "")
        query = ch.get("query", "")
        if url in urls:
            test_fail("Sin duplicados", f"URL duplicada para '{query}': {url}")
            return
        if query in queries:
            test_fail("Sin duplicados", f"Canal duplicado: {query}")
            return
        urls.append(url)
        queries.append(query)

    test_pass("Sin canales duplicados")


def test_single_quality():
    """Test 7: Only one quality per channel."""
    data = load_json_safe(IMPORTED_FILE)
    if not data:
        test_warn("Una calidad por canal", "No se encontró imported_channels.json")
        return

    query_counts = {}
    for ch in data.get("channels", []):
        q = ch.get("query", "")
        query_counts[q] = query_counts.get(q, 0) + 1

    duplicated = [q for q, count in query_counts.items() if count > 1]
    if duplicated:
        test_fail("Una calidad por canal", f"Canales con múltiples entradas: {duplicated}")
    else:
        test_pass("Una sola calidad por canal")


def test_m3u_well_formed():
    """Test 8-9: M3U attributes well-formed, no User-Agent in title."""
    if not os.path.exists(INDEX_FILE):
        test_warn("M3U bien formado", "No se encontró index.m3u")
        return

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Test 10: starts with #EXTM3U
    if content.strip().startswith("#EXTM3U"):
        test_pass("index.m3u comienza con #EXTM3U")
    else:
        test_fail("index.m3u comienza con #EXTM3U")

    # Check for User-Agent leaking into display name
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        if line.startswith("#EXTINF"):
            # The display name is after the last comma outside quotes
            # Check for common User-Agent patterns in the line after the last comma
            parts = line.split(",")
            if len(parts) >= 2:
                display = parts[-1].strip()
                if "mozilla" in display.lower() or "chrome" in display.lower() \
                        or "webkit" in display.lower() or "gecko" in display.lower():
                    test_fail("User-Agent no en título",
                              f"Línea {i}: User-Agent detectado en nombre: '{display[:80]}...'")
                    return
                # Check for group-title in display name
                if 'group-title="' in display.lower():
                    test_fail("group-title no en título",
                              f"Línea {i}: group-title en nombre visible: '{display[:80]}...'")
                    return

    test_pass("Atributos M3U bien formados (sin User-Agent ni group-title en título)")


def test_m3u_ss_iptv_compatible():
    """Test 11: SS IPTV compatibility."""
    if not os.path.exists(INDEX_FILE):
        test_warn("Compatibilidad SS IPTV", "No se encontró index.m3u")
        return

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # SS IPTV requires: #EXTM3U header, #EXTINF lines with tvg-id, tvg-name, group-title
    issues = []

    if not content.startswith("#EXTM3U"):
        issues.append("Falta encabezado #EXTM3U")

    # Check at least one EXTINF line has required attributes
    has_extinf = False
    for line in content.split("\n"):
        if line.startswith("#EXTINF"):
            has_extinf = True
            if 'tvg-id="' not in line:
                issues.append(f"Falta tvg-id en: {line[:60]}...")
                break
            if 'group-title="' not in line:
                issues.append(f"Falta group-title en: {line[:60]}...")
                break

    if not has_extinf:
        issues.append("No se encontraron líneas #EXTINF")

    if issues:
        test_fail("Compatibilidad SS IPTV", "; ".join(issues))
    else:
        test_pass("Compatible con SS IPTV")


def test_guatemala_in_playlist():
    """Verify Guatemala channels are in the final playlist."""
    if not os.path.exists(INDEX_FILE):
        test_warn("Guatemala en playlist", "No se encontró index.m3u")
        return

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        content = f.read().lower()

    required = ["canal 3", "canal 7", "tn23"]
    for ch_name in required:
        if ch_name in content:
            test_pass(f"'{ch_name}' presente en index.m3u")
        else:
            test_fail(f"'{ch_name}' presente en index.m3u")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  IPTV Guatemala - Pruebas de Importacion")
    print("=" * 60)
    print()

    test_json_validity()
    print()
    test_guatemala_channels_present()
    print()
    test_brazil_excluded()
    test_asia_europe_excluded()
    print()
    test_axn_priority()
    test_tnt_not_sports()
    print()
    test_no_duplicates()
    test_single_quality()
    print()
    test_m3u_well_formed()
    test_m3u_ss_iptv_compatible()
    print()
    test_guatemala_in_playlist()

    print()
    print("=" * 60)
    print(f"  Resultados: {passed} pasaron, {failed} fallaron, {warnings} advertencias")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
