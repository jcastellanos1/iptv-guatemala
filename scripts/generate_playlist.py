#!/usr/bin/env python3
"""
generate_playlist.py — Generador de lista M3U para IPTV Guatemala.

Lee data/channels.json (canales guatemaltecos) y data/imported_channels.json
(canales latinoamericanos de IPTV-org), filtra canales habilitados y funcionales,
y genera index.m3u en formato compatible con SS IPTV, VLC, Kodi y TiviMate.

Uso:
    python scripts/generate_playlist.py
"""

import json
import os
import sys
from datetime import datetime, timezone


# Rutas
BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CHANNELS_FILE = os.path.join(BASE_DIR, "data", "channels.json")
IMPORTED_FILE = os.path.join(BASE_DIR, "data", "imported_channels.json")
REPORT_FILE = os.path.join(BASE_DIR, "reports", "stream-status.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "index.m3u")

# Orden de grupos para la playlist
GROUP_ORDER = [
    "Guatemala",
    "TV abierta México",
    "TV abierta Colombia",
    "TV abierta Centroamérica",
    "TV abierta Sudamérica",
    "Noticias en español",
    "Películas y Series",
    "Entretenimiento",
    "Documentales",
    "Deportes",
    "Infantil",
    "Cultura y Educación",
    "Música",
    "Internacional en Español",
    "Otros Latinos",
]


def load_channels():
    """Carga los canales guatemaltecos desde channels.json."""
    channels_path = os.path.normpath(CHANNELS_FILE)
    if not os.path.exists(channels_path):
        print(f"ERROR: No se encontro {channels_path}")
        sys.exit(1)

    with open(channels_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("channels", [])


def load_imported_channels():
    """Carga los canales importados desde imported_channels.json (si existe)."""
    imported_path = os.path.normpath(IMPORTED_FILE)
    if not os.path.exists(imported_path):
        print("  INFO: No se encontro imported_channels.json. Solo se incluiran canales guatemaltecos.")
        return []

    with open(imported_path, "r", encoding="utf-8") as f:
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


def convert_imported_to_playlist_format(imported_channels):
    """
    Convert imported channel entries to the same format used by
    Guatemala channels for unified playlist generation.
    """
    converted = []
    for ch in imported_channels:
        # Skip channels that failed import
        if ch.get("validation_status") == "rejected_language":
            continue

        entry = {
            "id": ch.get("tvg_id", ""),
            "name": ch.get("display_name", ch.get("selected_name", "")),
            "logo": ch.get("tvg_logo", ""),
            "group": ch.get("category_final", "Otros Latinos"),
            "stream_url": ch.get("stream_url", ""),
            "enabled": True,
            "source": "iptv-org",
            "extra_lines": ch.get("extra_lines", []),
            "validation_status": ch.get("validation_status", "unknown"),
        }
        converted.append(entry)

    return converted


def validate_no_duplicates(channels):
    """Verifica que no existan IDs ni URLs duplicados."""
    ids_seen = {}
    urls_seen = {}
    errors = []

    for ch in channels:
        ch_id = ch.get("id")
        ch_url = ch.get("stream_url")
        ch_name = ch.get("name", "Unknown")

        # Verificar ID duplicado (skip empty IDs)
        if ch_id and ch_id in ids_seen:
            errors.append(f"ID duplicado '{ch_id}': '{ch_name}' y '{ids_seen[ch_id]}'")
        elif ch_id:
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
        extra_lines = channel.get("extra_lines", [])

        # Línea EXTINF con metadatos
        extinf = (
            f'#EXTINF:-1 tvg-id="{ch_id}" '
            f'tvg-name="{ch_name}" '
            f'tvg-logo="{ch_logo}" '
            f'group-title="{ch_group}"'
            f',{ch_name}'
        )
        lines.append(extinf)

        # Add extra lines (EXTVLCOPT for user-agent, referrer, etc.)
        for extra in extra_lines:
            lines.append(extra)

        lines.append(ch_url)
        lines.append("")  # Línea en blanco entre canales

    return "\n".join(lines)


def sort_channels_by_group(channels):
    """
    Sort channels by group order, then alphabetically within each group.
    Groups not in GROUP_ORDER go at the end.
    """
    def sort_key(ch):
        group = ch.get("group", "Guatemala")
        try:
            group_idx = GROUP_ORDER.index(group)
        except ValueError:
            group_idx = len(GROUP_ORDER)
        return (group_idx, ch.get("name", "").lower())

    return sorted(channels, key=sort_key)


def main():
    """Punto de entrada principal."""
    print("=" * 60)
    print("  IPTV Guatemala - Generador de Playlist M3U")
    print("=" * 60)
    print()

    # Cargar canales guatemaltecos
    gt_channels = load_channels()
    total_gt = len(gt_channels)
    print(f"  Canales guatemaltecos en la base de datos: {total_gt}")

    # Filtrar habilitados
    enabled_gt = [ch for ch in gt_channels if ch.get("enabled", False)]
    disabled_gt = total_gt - len(enabled_gt)
    print(f"  Canales guatemaltecos habilitados: {len(enabled_gt)}")

    # Cargar canales importados
    imported_raw = load_imported_channels()
    imported_channels = convert_imported_to_playlist_format(imported_raw)
    print(f"  Canales importados de IPTV-org: {len(imported_channels)}")

    # Combinar todos los canales
    all_channels = enabled_gt + imported_channels
    print(f"  Total de canales combinados: {len(all_channels)}")

    # Validar duplicados
    dup_errors = validate_no_duplicates(all_channels)
    if dup_errors:
        print()
        print("  [!] ADVERTENCIAS DE DUPLICADOS:")
        for err in dup_errors:
            print(f"    - {err}")
        print()
        # Don't exit on duplicates from imported channels — just warn

    # Cargar estado de validación
    stream_status = load_stream_status()

    # Filtrar canales caídos definitivamente (DNS, 404, 410)
    # Los canales con error 403 (geoblocking) o timeouts no se marcan como caídos en validate_streams.py
    final_channels = []
    excluded_offline = []
    for ch in all_channels:
        ch_id = ch.get("id")
        source = ch.get("source", "local")

        if source == "iptv-org":
            # For imported channels, include even if temporarily offline
            # They have their own validation status
            final_channels.append(ch)
        else:
            # For Guatemala channels, check stream status
            if stream_status and ch_id in stream_status:
                if not stream_status[ch_id]:
                    excluded_offline.append(ch.get("name", ch_id))
                    continue
            final_channels.append(ch)

    if excluded_offline:
        print(f"  Excluidos por estar caidos definitivamente (DNS/404/410): {len(excluded_offline)}")
        for name in excluded_offline:
            print(f"    - {name}")

    # Sort by group order
    final_channels = sort_channels_by_group(final_channels)

    if not final_channels:
        print()
        print("  [!] No hay canales para incluir en la lista.")
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
    print(f"    Canales guatemaltecos:     {len(enabled_gt)}")
    print(f"    Canales importados:        {len(imported_channels)}")
    print(f"    Total en playlist:         {len(final_channels)}")
    print(f"    Canales deshabilitados:    {disabled_gt}")
    print(f"    Canales caidos (DNS/404/410): {len(excluded_offline)}")
    print()
    print(f"  Archivo: {output_path}")
    print()

    # Show channels by group
    current_group = None
    for ch in final_channels:
        group = ch.get("group", "Sin grupo")
        if group != current_group:
            current_group = group
            print(f"  [{group}]")
        print(f"    - {ch.get('name')}")

    print("-" * 60)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n  Generado: {now_utc}")

    sys.exit(0)


if __name__ == "__main__":
    main()
