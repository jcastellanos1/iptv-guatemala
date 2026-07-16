# 📺 IPTV Guatemala

Lista M3U gratuita y pública de canales de televisión abierta de Guatemala, compatible con **SS IPTV**, **VLC**, **Kodi**, **TiviMate** y otros reproductores M3U.

> **⚠️ Este proyecto no aloja ni distribuye contenido audiovisual.** Únicamente enlaza transmisiones públicas y gratuitas accesibles sin jcastellanos1 ni contraseña. La disponibilidad de cada canal depende de terceros.

---

## 🔗 URL Directa de la Lista

```
https://jcastellanos1.github.io/iptv-guatemala/index.m3u
```

Copia esta URL y pégala en tu reproductor favorito.

---

## 📋 Canales Disponibles

| Canal | Categoría | Estado | Fuente Pública |
|---|---|---|---|
| Canal 3 Guatemala | General | 🟢 En línea | [ChapinTV](https://www.chapintv.com/) |
| Canal 7 Guatemala | General | 🟢 En línea | [ChapinTV](https://www.chapintv.com/) |
| TN23 Guatemala | Noticias | 🟢 En línea | [ChapinTV](https://www.chapintv.com/) |

> **Nota:** El estado de los canales se verifica automáticamente cada 6 horas. Los enlaces pueden cambiar sin previo aviso por decisión de los propios canales.

---

## 📺 Instrucciones por Reproductor

### SS IPTV (LG webOS / Samsung)

1. Abre **SS IPTV** en tu televisor.
2. Ve a **Configuración** (⚙️).
3. Obtén el **código de conexión** que aparece en pantalla.
4. En tu computadora, abre el editor de listas de SS IPTV:
   - `https://ss-iptv.com/users/playlist`
5. Ingresa el código de conexión.
6. Selecciona **Agregar lista externa**.
7. En **Nombre**, escribe: `IPTV Guatemala`
8. En **URL**, pega:
   ```
   https://jcastellanos1.github.io/iptv-guatemala/index.m3u
   ```
9. Haz clic en **Guardar**.
10. En el televisor, reinicia o actualiza SS IPTV.
11. La lista **IPTV Guatemala** aparecerá en la pantalla principal.
12. Ábrela y selecciona el canal que desees ver.

> **Importante:** No necesitas agregar los canales uno por uno. La lista completa se carga automáticamente.

---

### VLC Media Player (Windows / Mac / Linux)

1. Abre **VLC**.
2. Ve a **Medio** → **Abrir ubicación de red** (Ctrl+N).
3. Pega la URL:
   ```
   https://jcastellanos1.github.io/iptv-guatemala/index.m3u
   ```
4. Haz clic en **Reproducir**.
5. Para ver la lista de canales: **Ver** → **Lista de reproducción**.

---

### Kodi

1. Instala el add-on **PVR IPTV Simple Client** desde el repositorio oficial de Kodi.
2. Ve a **Configuración** → **PVR & Live TV** → **General** → **Activar**.
3. En **PVR IPTV Simple Client** → **Configurar**:
   - **Ubicación de la lista M3U:** URL remota
   - **URL de la lista M3U:**
     ```
     https://jcastellanos1.github.io/iptv-guatemala/index.m3u
     ```
4. Reinicia Kodi.
5. Ve a **TV** en el menú principal para ver los canales.

---

### TiviMate (Android TV / Fire TV)

1. Abre **TiviMate**.
2. Ve a **Configuración** → **Playlists** → **Agregar playlist**.
3. Selecciona **M3U playlist**.
4. Ingresa la URL:
   ```
   https://jcastellanos1.github.io/iptv-guatemala/index.m3u
   ```
5. Sigue las instrucciones para completar la configuración.

---

## 🛠️ Ejecución Local de los Scripts

### Requisitos

- Python 3.8 o superior
- pip

### Instalación

```bash
# Clonar el repositorio
git clone https://github.com/jcastellanos1/iptv-guatemala.git
cd iptv-guatemala

# Instalar dependencias
pip install -r scripts/requirements.txt
```

### Validar streams

```bash
python scripts/validate_streams.py
```

Esto verifica cada canal HLS y genera un reporte en `reports/stream-status.json`.

### Generar la lista M3U

```bash
python scripts/generate_playlist.py
```

Esto genera `index.m3u` a partir de `data/channels.json`, excluyendo canales deshabilitados o fuera de línea.

---

## ➕ Cómo Agregar un Nuevo Canal

1. Verifica que el canal tenga una transmisión HLS pública (`.m3u8`) accesible sin autenticación.
2. Confirma que se reproduce correctamente en VLC u otro reproductor.
3. Edita `data/channels.json` y agrega una nueva entrada:

```json
{
  "id": "NuevoCanal.gt",
  "name": "Nuevo Canal Guatemala",
  "country": "GT",
  "category": "General",
  "group": "Guatemala",
  "stream_url": "https://ejemplo.com/stream.m3u8",
  "source_page": "https://sitio-oficial-del-canal.com",
  "logo": "https://jcastellanos1.github.io/iptv-guatemala/logos/nuevo-canal.png",
  "enabled": true,
  "notes": "Descripción de la fuente pública."
}
```

4. Agrega el logo en `logos/` (PNG, ~400×400px).
5. Ejecuta `python scripts/validate_streams.py` para verificar.
6. Ejecuta `python scripts/generate_playlist.py` para regenerar la lista.
7. Haz commit y push. El workflow de GitHub Actions también ejecutará la validación automáticamente.

---

## 🔄 Cómo Reemplazar un Enlace Caído

1. Busca la nueva URL HLS pública del canal.
2. Edita `data/channels.json` y actualiza el campo `stream_url`.
3. Actualiza las notas con la nueva fuente.
4. Ejecuta la validación:
   ```bash
   python scripts/validate_streams.py
   python scripts/generate_playlist.py
   ```
5. Haz commit y push.

---

## 🐛 Reportar Problemas

Si un canal no funciona o tienes sugerencias:

1. Abre un [Issue en GitHub](https://github.com/jcastellanos1/iptv-guatemala/issues/new).
2. Incluye:
   - Nombre del canal afectado.
   - Error observado (si aplica).
   - Reproductor utilizado.
   - Fecha y hora del problema.

---

## 🤝 Cómo Contribuir

1. Haz fork del repositorio.
2. Crea una rama: `git checkout -b agregar-canal-x`
3. Agrega el canal siguiendo las instrucciones de arriba.
4. Verifica que funcione localmente.
5. Abre un Pull Request con:
   - Nombre del canal.
   - URL HLS.
   - Fuente pública donde se reproduce.
   - Captura de pantalla de la reproducción (opcional pero recomendado).

### Reglas para Contribuir

- ✅ Solo transmisiones HLS públicas y gratuitas.
- ✅ Fuentes verificables (sitios oficiales o públicos).
- ❌ No canales premium, pirata o con credenciales.
- ❌ No enlaces de proveedores Xtream Codes.
- ❌ No señales privadas o con DRM.
- ❌ No enlaces que expiren en minutos.

---

## ⚖️ Información Legal

### Licencia

El código fuente (scripts, configuración, estructura del repositorio) está licenciado bajo la [Licencia MIT](LICENSE).

La licencia **no cubre** las transmisiones de video, los logos, las marcas de los canales ni los contenidos audiovisuales. Los logos se utilizan únicamente con fines identificativos. Todas las marcas pertenecen a sus respectivos propietarios.

### Aviso de Disponibilidad

- Este repositorio **no aloja video**. Solo enlaza transmisiones públicas.
- La disponibilidad de cada canal depende de decisiones de los propios canales y sus proveedores de infraestructura.
- **No se garantiza el funcionamiento permanente** de ningún enlace.
- Los enlaces pueden cambiar o dejar de funcionar en cualquier momento.
- Este proyecto **no está afiliado** con ninguno de los canales listados.

### Política de Retiro de Contenido

Si eres titular legítimo de los derechos de una señal incluida en esta lista y deseas que sea retirada:

1. Abre un [Issue en GitHub](https://github.com/jcastellanos1/iptv-guatemala/issues/new) indicando:
   - Nombre del canal.
   - Tu relación con el canal (titular, representante legal, etc.).
   - La URL que deseas retirar.
2. Se retirará **inmediatamente** tras verificar la solicitud.

También puedes contactar al mantenedor del proyecto a través de GitHub Issues.

### Uso Exclusivo de Fuentes Legítimas

- Todos los enlaces provienen de transmisiones públicas accesibles sin autenticación.
- No se utilizaron credenciales, servicios IPTV pirata, Xtream Codes ni señales privadas.
- No se evadieron controles de acceso, DRM ni restricciones geográficas.
- Las fuentes se documentan para cada canal en `data/channels.json`.

---

## 🔧 Automatización

Este repositorio utiliza **GitHub Actions** para:

- ✅ Validar automáticamente los streams cada 6 horas.
- ✅ Regenerar `index.m3u` excluyendo canales caídos.
- ✅ Actualizar `reports/stream-status.json` con el estado de cada canal.
- ✅ Hacer commit automático solo cuando hay cambios.

El workflow también se ejecuta manualmente (`workflow_dispatch`) y al modificar `data/channels.json`, `scripts/**` o `logos/**`.

---

## 📅 Última Verificación

Consulta `reports/stream-status.json` para ver la fecha y el resultado de la última validación automática.

---

**Hecho con ❤️ para la comunidad guatemalteca.**
