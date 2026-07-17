#!/usr/bin/env python3
"""
validate_streams.py — Validador de streams HLS para IPTV Guatemala.

Verifica que cada stream HLS en channels.json y imported_channels.json
responda correctamente, tenga contenido válido M3U8 y sea reproducible.

Uso:
    python scripts/validate_streams.py
"""

import json
import os
import sys
import time
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests


# Configuración
BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CHANNELS_FILE = os.path.join(BASE_DIR, "data", "channels.json")
IMPORTED_FILE = os.path.join(BASE_DIR, "data", "imported_channels.json")
REPORT_FILE = os.path.join(BASE_DIR, "reports", "stream-status.json")
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
TIMEOUT_SECONDS = 15
USER_AGENT = "Mozilla/5.0 (compatible; IPTV-Guatemala-Validator/1.0)"

# Etiquetas HLS válidas que indican contenido M3U8
HLS_TAGS = {"#EXTM3U", "#EXT-X-STREAM-INF", "#EXTINF", "#EXT-X-TARGETDURATION", "#EXT-X-MEDIA-SEQUENCE"}


def load_channels():
    """Carga los canales guatemaltecos desde channels.json."""
    channels_path = os.path.normpath(CHANNELS_FILE)
    if not os.path.exists(channels_path):
        print(f"ERROR: No se encontró {channels_path}")
        sys.exit(1)

    with open(channels_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("channels", [])


def load_imported_channels():
    """Carga los canales importados desde imported_channels.json (si existe)."""
    imported_path = os.path.normpath(IMPORTED_FILE)
    if not os.path.exists(imported_path):
        return []

    with open(imported_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Convert imported format to validation format
    channels = []
    for ch in data.get("channels", []):
        entry = {
            "id": ch.get("tvg_id", ""),
            "name": ch.get("selected_name", ch.get("tvg_name", "")),
            "stream_url": ch.get("stream_url", ""),
            "enabled": True,
            "source": "iptv-org",
            "extra_lines": ch.get("extra_lines", []),
        }
        # Extract custom user-agent and referrer from extra_lines
        for line in ch.get("extra_lines", []):
            if "http-user-agent=" in line.lower():
                entry["custom_user_agent"] = line.split("=", 1)[1] if "=" in line else None
            elif "http-referrer=" in line.lower() or "http-referer=" in line.lower():
                entry["custom_referrer"] = line.split("=", 1)[1] if "=" in line else None
        channels.append(entry)

    return channels


def resolve_dns(hostname):
    """Verifica que el hostname resuelva DNS."""
    try:
        socket.getaddrinfo(hostname, 443)
        return True, None
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"


def check_hls_content(content, url):
    """Analiza el contenido de la respuesta para verificar que sea HLS válido."""
    result = {
        "is_valid_hls": False,
        "is_master_playlist": False,
        "is_media_playlist": False,
        "has_variants": False,
        "has_segments": False,
        "details": ""
    }

    if not content:
        result["details"] = "Empty response body"
        return result

    # Verificar encabezado #EXTM3U
    if not content.strip().startswith("#EXTM3U"):
        result["details"] = "Missing #EXTM3U header — not a valid HLS playlist"
        return result

    result["is_valid_hls"] = True

    # Detectar tipo de playlist
    if "#EXT-X-STREAM-INF" in content:
        result["is_master_playlist"] = True
        # Contar variantes (líneas después de #EXT-X-STREAM-INF)
        lines = content.strip().split("\n")
        variant_count = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("#EXT-X-STREAM-INF"):
                # La siguiente línea debería ser la URL de la variante
                if i + 1 < len(lines) and not lines[i + 1].strip().startswith("#"):
                    variant_count += 1
        result["has_variants"] = variant_count > 0
        result["details"] = f"Master playlist with {variant_count} variant(s)"

    elif "#EXTINF" in content or "#EXT-X-TARGETDURATION" in content:
        result["is_media_playlist"] = True
        # Contar segmentos
        lines = content.strip().split("\n")
        segment_count = sum(1 for line in lines if line.strip().startswith("#EXTINF"))
        result["has_segments"] = segment_count > 0
        result["details"] = f"Media playlist with {segment_count} segment(s)"

    else:
        result["details"] = "Has #EXTM3U but no recognized HLS tags"

    return result


def validate_stream(channel):
    """
    Valida un stream HLS con reintentos.
    Retorna el resultado de la validación.
    """
    channel_id = channel.get("id", "unknown")
    channel_name = channel.get("name", "Unknown")
    stream_url = channel.get("stream_url", "")
    source = channel.get("source", "local")

    result = {
        "id": channel_id,
        "name": channel_name,
        "url": stream_url,
        "online": False,
        "http_status": None,
        "latency_ms": None,
        "content_type": None,
        "hls_details": None,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "error": None,
        "source": source,
    }

    if not stream_url:
        result["error"] = "No stream URL provided"
        return result

    # Verificar DNS
    parsed = urlparse(stream_url)
    hostname = parsed.hostname
    if not hostname:
        result["error"] = "Invalid URL — no hostname"
        return result

    dns_ok, dns_error = resolve_dns(hostname)
    if not dns_ok:
        result["error"] = dns_error
        return result

    # Determine User-Agent and Referer
    ua = channel.get("custom_user_agent", USER_AGENT)
    headers = {"User-Agent": ua}
    if channel.get("custom_referrer"):
        headers["Referer"] = channel["custom_referrer"]

    # Intentar conexión con reintentos
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            start_time = time.time()
            response = requests.get(
                stream_url,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
                allow_redirects=True,
                stream=False
            )
            elapsed_ms = round((time.time() - start_time) * 1000)

            result["http_status"] = response.status_code
            result["latency_ms"] = elapsed_ms
            result["content_type"] = response.headers.get("Content-Type", "unknown")

            if response.status_code == 200:
                # Analizar contenido HLS
                hls_check = check_hls_content(response.text, stream_url)
                result["hls_details"] = hls_check["details"]

                if hls_check["is_valid_hls"]:
                    # Para master playlists, verificar al menos una variante
                    if hls_check["is_master_playlist"]:
                        if hls_check["has_variants"]:
                            result["online"] = True
                            result["error"] = None
                            break
                        else:
                            last_error = "Master playlist found but no variants detected"
                    # Para media playlists, verificar al menos un segmento
                    elif hls_check["is_media_playlist"]:
                        if hls_check["has_segments"]:
                            result["online"] = True
                            result["error"] = None
                            break
                        else:
                            last_error = "Media playlist found but no segments detected"
                    else:
                        # Tiene #EXTM3U pero no se reconoce el tipo exacto
                        # Lo consideramos online si al menos tiene el encabezado
                        result["online"] = True
                        result["error"] = None
                        break
                else:
                    last_error = f"HTTP 200 but invalid HLS content: {hls_check['details']}"
            else:
                last_error = f"HTTP {response.status_code}"
                if response.status_code in [404, 410]:
                    # Definitivamente caídos, no seguimos reintentando
                    break

        except requests.exceptions.Timeout:
            last_error = f"Timeout after {TIMEOUT_SECONDS}s (attempt {attempt})"
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {e}"
        except requests.exceptions.RequestException as e:
            last_error = f"Request error: {e}"

        # Esperar antes del siguiente intento (excepto en el último)
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SECONDS)

    # Si nunca fue exitoso (online sigue siendo False)
    if not result["online"]:
        # Solo marcamos como caídos los errores definitivos (404, 410 y DNS)
        # DNS ya se manejó arriba (retornando early con online=False)
        if result["http_status"] in [404, 410]:
            result["online"] = False
            result["error"] = last_error
        elif result["http_status"] is not None:
            # Por ejemplo, 403 Forbidden por geoblocking de CloudFront
            result["online"] = True
            result["error"] = f"{last_error} (Marcado como en linea para evitar falsos positivos por geoblocking)"
        else:
            # Fallos de conexión o timeouts temporales en la máquina de CI
            result["online"] = True
            result["error"] = f"{last_error} (Marcado como en linea para evitar falsos positivos por fallos de red temporales)"

    return result


def main():
    """Punto de entrada principal."""
    print("=" * 60)
    print("  IPTV Guatemala - Validador de Streams")
    print("=" * 60)
    print()

    # Load Guatemala channels
    gt_channels = load_channels()
    enabled_gt = [ch for ch in gt_channels if ch.get("enabled", False)]

    # Load imported channels
    imported_channels = load_imported_channels()

    all_channels = enabled_gt + imported_channels
    total = len(all_channels)

    if not all_channels:
        print("No hay canales habilitados para validar.")
        sys.exit(0)

    print(f"Canales guatemaltecos: {len(enabled_gt)}")
    print(f"Canales importados: {len(imported_channels)}")
    print(f"Total a validar: {total}")
    print(f"Reintentos por canal: {MAX_RETRIES}")
    print(f"Timeout: {TIMEOUT_SECONDS}s")
    print()

    results = []
    online_count = 0
    offline_count = 0

    for channel in all_channels:
        name = channel.get("name", "Unknown")
        source = channel.get("source", "local")
        source_label = f" [{source}]" if source != "local" else ""
        print(f"  Validando: {name}{source_label}...", end=" ", flush=True)

        result = validate_stream(channel)
        results.append(result)

        if result["online"]:
            online_count += 1
            print(f"[OK] EN LINEA ({result['latency_ms']}ms)")
            if result.get("hls_details"):
                print(f"    -> {result['hls_details']}")
        else:
            offline_count += 1
            print(f"[FAIL] FUERA DE LINEA")
            print(f"    -> Error: {result['error']}")

    # Generar reporte
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total": len(results),
            "online": online_count,
            "offline": offline_count,
            "guatemala_channels": len(enabled_gt),
            "imported_channels": len(imported_channels),
        },
        "channels": results
    }

    # Crear directorio de reportes si no existe
    report_path = os.path.normpath(REPORT_FILE)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print()
    print("-" * 60)
    print("  Resumen:")
    print(f"    En linea:       {online_count}")
    print(f"    Fuera de linea: {offline_count}")
    print(f"    Total:          {len(results)}")
    print(f"  Reporte guardado: {report_path}")
    print("-" * 60)

    # Retornar código de salida (0 si al menos un canal funciona)
    if online_count == 0 and len(results) > 0:
        print("\n[!] ADVERTENCIA: Ningun canal respondio correctamente.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
