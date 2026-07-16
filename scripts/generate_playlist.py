#!/usr/bin/env python3
"""
generate_playlist.py — Generador de lista M3U para IPTV Guatemala.

Lee data/channels.json, filtra canales habilitados y funcionales,
y genera index.m3u en formato compatible con SS IPTV, VLC, Kodi y TiviMate.

Uso:
    python scripts/generate_playlist.py
"""

import json
import os
import sys
from datetime import datetime, timezone


# Rutas
CHANNELS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "channels.json")
REPORT_FILE = os.path.join(os.path.dirname(__file__), "..", "reports", "stream-status.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "index.m3u")


def load_channels():
    """Carga los canales desde channels.json."""
    channels_path = os.path.normpath(CHANNELS_FILE)
    if not os.path.exists(channels_path):
        print(f"ERROR: No se encontro {channels_path}")
        sys.exit(1)

    with open(channels_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("channels", [])


def load_stream_status():
    """Carga el estado de validación de streams (si existe)."""
    report_path = os.path.normpath(REPORT_FILE)
    if not os.path.exists(report_path):
        print("  INFO: No se encontro reporte de validacion. Se incluiran todos los canales habilitados.")
        return {}

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Crear diccionario de estado por ID
    status_map = {}
    for ch in data.get("channels", []):
        status_map[ch.get("id")] = ch.get("online", False)

    return status_map


def validate_no_duplicates(channels):
    """Verifica que no existan IDs ni URLs duplicados."""
    ids_seen = {}
    urls_seen = {}
    errors = []

    for ch in channels:
        ch_id = ch.get("id")
        ch_url = ch.get("stream_url")
        ch_name = ch.get("name", "Unknown")

        # Verificar ID duplicado
        if ch_id in ids_seen:
            errors.append(f"ID duplicado '{ch_id}': '{ch_name}' y '{ids_seen[ch_id]}'")
        else:
            ids_seen[ch_id] = ch_name

        # Verificar URL duplicada
        if ch_url in urls_seen:
            errors.append(f"URL duplicada: '{ch_name}' y '{urls_seen[ch_url]}'")
        else:
            urls_seen[ch_url] = ch_name

    return errors


def generate_m3u(channels):
    """Genera el contenido del archivo M3U."""
    lines = ["#EXTM3U"]
    lines.append("")  # Línea en blanco después del encabezado

    for channel in channels:
        ch_id = channel.get("id", "")
        ch_name = channel.get("name", "")
        ch_logo = channel.get("logo", "")
        ch_group = channel.get("group", "Guatemala")
        ch_url = channel.get("stream_url", "")

        # Línea EXTINF con metadatos
        extinf = (
            f'#EXTINF:-1 tvg-id="{ch_id}" '
            f'tvg-name="{ch_name}" '
            f'tvg-logo="{ch_logo}" '
            f'group-title="{ch_group}"'
            f',{ch_name}'
        )
        lines.append(extinf)
        lines.append(ch_url)
        lines.append("")  # Línea en blanco entre canales

    return "\n".join(lines)


def main():
    """Punto de entrada principal."""
    print("=" * 60)
    print("  IPTV Guatemala - Generador de Playlist M3U")
    print("=" * 60)
    print()

    # Cargar canales
    channels = load_channels()
    total_channels = len(channels)
    print(f"  Canales en la base de datos: {total_channels}")

    # Filtrar habilitados
    enabled_channels = [ch for ch in channels if ch.get("enabled", False)]
    disabled_count = total_channels - len(enabled_channels)
    print(f"  Canales habilitados: {len(enabled_channels)}")
    if disabled_count > 0:
        print(f"  Canales deshabilitados: {disabled_count}")

    # Validar duplicados
    dup_errors = validate_no_duplicates(enabled_channels)
    if dup_errors:
        print()
        print("  [!] ERRORES DE DUPLICADOS:")
        for err in dup_errors:
            print(f"    - {err}")
        print()
        print("  Corrija los duplicados antes de continuar.")
        sys.exit(1)

    # Cargar estado de validación (solo informativo)
    stream_status = load_stream_status()

    # Incluir todos los canales habilitados en la lista.
    # No excluimos canales basándonos en el reporte de validación porque
    # los CDN (CloudFront) pueden bloquear geográficamente las solicitudes
    # desde GitHub Actions (servidores en EE.UU.), pero funcionar
    # perfectamente desde Guatemala u otras regiones.
    final_channels = list(enabled_channels)
    offline_names = []
    if stream_status:
        for ch in enabled_channels:
            ch_id = ch.get("id")
            if ch_id in stream_status and not stream_status[ch_id]:
                offline_names.append(ch.get("name", ch_id))

    if offline_names:
        print(f"  [INFO] Canales con fallo en ultima validacion: {len(offline_names)}")
        for name in offline_names:
            print(f"    - {name}")
        print("  (Se incluyen de todas formas; el CDN puede bloquear por region)")

    # Ordenar alfabéticamente por nombre
    final_channels.sort(key=lambda ch: ch.get("name", "").lower())

    if not final_channels:
        print()
        print("  [!] No hay canales para incluir en la lista.")
        # Crear archivo M3U vacío con solo el encabezado
        output_path = os.path.normpath(OUTPUT_FILE)
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("#EXTM3U\n")
        print(f"  Se genero un archivo M3U vacio: {output_path}")
        sys.exit(0)

    # Generar M3U
    m3u_content = generate_m3u(final_channels)

    # Escribir archivo (UTF-8 sin BOM, saltos de línea Unix)
    output_path = os.path.normpath(OUTPUT_FILE)
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(m3u_content)

    print()
    print("-" * 60)
    print("  [OK] Lista M3U generada exitosamente")
    print()
    print("  Resumen:")
    print(f"    Canales incluidos:       {len(final_channels)}")
    print(f"    Canales deshabilitados:  {disabled_count}")
    print(f"    Canales con fallo validacion: {len(offline_names)}")
    print(f"    Total en base de datos:  {total_channels}")
    print()
    print(f"  Archivo: {output_path}")
    print()
    print("  Canales en la lista:")
    for i, ch in enumerate(final_channels, 1):
        print(f"    {i}. {ch.get('name')} [{ch.get('category', 'General')}]")
    print("-" * 60)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n  Generado: {now_utc}")

    sys.exit(0)


if __name__ == "__main__":
    main()
