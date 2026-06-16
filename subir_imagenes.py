"""
subir_imagenes.py
-----------------
Sube las imágenes de output/images/ al media manager del portal destino
y actualiza los placeholders [aquí va X] en output/pagina.html y
output/pagina_styled.html con las <img src="URL"> reales.

Ejecución:
  python subir_imagenes.py
"""

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
import os
import json
import config

MEDIA_MANAGER_URL = "https://soluciones.docs.inditex.com/admin/media-manager"

# Endpoint descubierto mediante captura de red (10/06/2026)
UPLOAD_ENDPOINT = "https://soluciones.docs.inditex.com/api/v1/admin/sources?folder=image&fileTypeId=1&isPublic=true"
BASE_URL = "https://soluciones.docs.inditex.com"

EXTS_IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}

# Selectores candidatos para el botón de subida (se prueban en orden)
SELECTORES_UPLOAD = [
    "input[type='file']",
    "button:has-text('Upload')",
    "button:has-text('Subir')",
    "button:has-text('Add media')",
    "button:has-text('Añadir')",
    "button:has-text('New')",
    "button:has-text('Nueva')",
    "[aria-label*='upload' i]",
    "[data-testid*='upload']",
    "[class*='upload' i]",
]

# Campos candidatos de la respuesta JSON donde suele venir la URL
CAMPOS_URL = [
    "staticPublicUrl", "publicUrl", "public_url",
    "url", "src", "imageUrl", "image_url",
    "fileUrl", "file_url", "cdnUrl", "cdn_url",
    "permalink", "link", "filePath", "path",
]


def _extraer_url_de_respuesta(data) -> str | None:
    """Busca recursivamente una URL de imagen en un objeto JSON."""
    if isinstance(data, str):
        if data.startswith("http") and any(ext in data for ext in EXTS_IMAGEN):
            return data
        return None

    if isinstance(data, dict):
        # Primero campos conocidos
        for campo in CAMPOS_URL:
            val = data.get(campo)
            if isinstance(val, str):
                if val.startswith("http"):
                    return val
                # filePath relativo → construir URL completa
                if val and not val.startswith("{"):
                    return BASE_URL + "/" + val.lstrip("/")
        # Luego búsqueda recursiva
        for v in data.values():
            resultado = _extraer_url_de_respuesta(v)
            if resultado:
                return resultado

    if isinstance(data, list):
        for item in data:
            resultado = _extraer_url_de_respuesta(item)
            if resultado:
                return resultado

    return None


def actualizar_html_con_urls(mapping: dict):
    """Sustituye [aquí va X] por <img src="URL"> en pagina.html y pagina_styled.html."""
    for nombre_html in ["pagina.html", "pagina_styled.html"]:
        ruta = os.path.join(config.OUTPUT_DIR, nombre_html)
        if not os.path.exists(ruta):
            continue
        with open(ruta, "r", encoding="utf-8") as f:
            html = f.read()

        reemplazos = 0
        for nombre_base, info in mapping.items():
            # Soportar tanto formato nuevo {url, id, fileLink} como legado (string URL)
            url_remota = info["url"] if isinstance(info, dict) else info
            placeholder = f"[aquí va {nombre_base}]"
            if placeholder not in html:
                continue
            tag_img = f'<img src="{url_remota}" alt="{nombre_base}" style="max-width:100%;">'
            html = html.replace(f"<p>{placeholder}</p>", f"<p>{tag_img}</p>")
            html = html.replace(placeholder, tag_img)
            reemplazos += 1

        with open(ruta, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  [{nombre_html}] {reemplazos} placeholder(s) sustituido(s).")


def _diagnosticar_pagina(page):
    """Toma screenshot y lista TODOS los elementos con texto para identificar selectores."""
    # Screenshot para inspección visual
    screenshot_path = os.path.join(config.OUTPUT_DIR, "media_manager_screenshot.png")
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"    Screenshot guardado en: {screenshot_path}")

    # Esperar un poco más por si la página carga en diferido
    page.wait_for_timeout(3000)

    # Listar todos los elementos con contenido visible (sin filtrar por tag)
    elementos = page.evaluate("""() => {
        const info = [];
        document.querySelectorAll('*').forEach(el => {
            const tag = el.tagName.toLowerCase();
            if (!['script','style','head','meta','link','br','hr'].includes(tag)) {
                const text = (el.innerText || '').trim().slice(0, 80);
                const ariaLabel = el.getAttribute('aria-label') || '';
                const role = el.getAttribute('role') || '';
                const testId = el.getAttribute('data-testid') || '';
                const cls = el.className ? el.className.toString().slice(0, 60) : '';
                if (text || ariaLabel || role === 'button') {
                    info.push({ tag, text, ariaLabel, role, testId, cls, id: el.id || '' });
                }
            }
        });
        return info.slice(0, 50);
    }""")
    print("    ── Elementos con contenido en la página ──")
    for el in elementos:
        partes = [f"<{el['tag']}>"]
        if el['role']:   partes.append(f"role={el['role']}")
        if el['text']:   partes.append(f"'{el['text']}'")
        if el['ariaLabel']: partes.append(f"aria-label='{el['ariaLabel']}'")
        if el['testId']: partes.append(f"data-testid='{el['testId']}'")
        if el['id']:     partes.append(f"id='{el['id']}'")
        if el['cls']:    partes.append(f"class='{el['cls']}'")
        print("      " + "  ".join(partes))
    print("    ──────────────────────────────────────────")


def _extraer_token(page) -> str | None:
    """Extrae el JWT de acceso del localStorage/sessionStorage del navegador."""
    return page.evaluate("""() => {
        for (const store of [localStorage, sessionStorage]) {
            for (const key of Object.keys(store)) {
                const raw = store.getItem(key);
                if (!raw) continue;
                // Valor JWT directo
                if (raw.startsWith('eyJ')) return raw;
                // Objeto JSON con access_token
                try {
                    const obj = JSON.parse(raw);
                    if (obj && obj.access_token) return obj.access_token;
                    if (obj && obj.token) return obj.token;
                    if (obj && obj.id_token) return obj.id_token;
                } catch {}
            }
        }
        return null;
    }""")


def _subir_via_api(page, context, ruta_local: str, folder_id: str) -> str | None:
    """Sube directamente a la API del portal usando el token y cookies del navegador."""
    import requests as req

    token = _extraer_token(page)
    cookies = {c["name"]: c["value"] for c in context.cookies()
               if "inditex.com" in c.get("domain", "")}

    headers = {"Authorization": f"Bearer {token}"} if token else {}

    base = "https://soluciones.docs.inditex.com"
    nombre = os.path.basename(ruta_local)
    ext = os.path.splitext(nombre)[1].lstrip(".").lower() or "png"
    mime = f"image/{ext}"

    for endpoint in ["/api/v1/medias", "/api/v1/media", "/api/v1/files", "/api/v1/upload"]:
        try:
            with open(ruta_local, "rb") as f:
                files = {"file": (nombre, f, mime)}
                data = {"folder": folder_id} if folder_id else {}
                resp = req.post(base + endpoint, headers=headers,
                                files=files, data=data, cookies=cookies, timeout=30)
            if resp.status_code in (200, 201):
                try:
                    url = _extraer_url_de_respuesta(resp.json())
                    if url:
                        print(f"    [API directa → {endpoint}]")
                        return url
                except Exception:
                    pass
        except Exception:
            continue
    return None


def _intentar_subir(page, ruta_local: str) -> bool:
    """
    Intenta subir usando el file chooser nativo (compatible con React).
    Devuelve True si se disparó la subida, False si hay que hacerlo manualmente.
    """
    # Buscar TODOS los input[type=file] y hacer click para abrir el file chooser
    for selector in ["input[type='file']"] + SELECTORES_UPLOAD[1:]:
        elementos = page.query_selector_all(selector)
        for el in elementos:
            try:
                with page.expect_file_chooser(timeout=3000) as fc_info:
                    el.click()
                fc_info.value.set_files(ruta_local)
                return True
            except PwTimeout:
                continue
            except Exception:
                continue

    # Nada encontrado → mostrar diagnóstico
    _diagnosticar_pagina(page)
    return False


def subir_imagenes():
    img_dir = os.path.join(config.OUTPUT_DIR, "images")
    if not os.path.exists(img_dir):
        print(f"ERROR: No existe la carpeta '{img_dir}'.")
        print("Ejecuta primero 'python main.py' para generar las imágenes.")
        return

    imagenes = sorted(
        f for f in os.listdir(img_dir)
        if os.path.splitext(f)[1].lower() in EXTS_IMAGEN
    )

    if not imagenes:
        print("No hay imágenes en output/images/ para subir.")
        return

    print(f"Imágenes a subir: {len(imagenes)}")

    mapping = {}   # nombre_base → URL remota

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # ── Interceptar TODAS las peticiones ─────────────────────────────────
        red_log = []

        def on_request(request):
            red_log.append({"req_url": request.url, "method": request.method, "resp": None})

        def on_response(response):
            if response.status not in (200, 201, 202):
                return
            entry = next(
                (e for e in reversed(red_log) if e["req_url"] == response.url and e["resp"] is None),
                None
            )
            ct = response.headers.get("content-type", "")
            data = None
            if "json" in ct:
                try:
                    data = response.json()
                except Exception:
                    pass
            info = {"status": response.status, "ct": ct, "data": data, "url": response.url}
            if entry:
                entry["resp"] = info
            else:
                red_log.append({"req_url": response.url, "method": "?", "resp": info})

        page.on("request", on_request)
        page.on("response", on_response)

        # ── Navegar al media manager ──────────────────────────────────────────
        print("\nAbriendo media manager…")
        print("→ Si aparece login, autentícate con tu cuenta corporativa en el navegador.")
        print("→ Una vez en la página del media manager, el script continuará solo.\n")

        page.goto(MEDIA_MANAGER_URL, timeout=60_000)

        # Esperar a que el SSO redirija de vuelta a la app (hasta 2 min)
        try:
            page.wait_for_url("**/admin/**", timeout=300_000)
        except PwTimeout:
            print("Tiempo de espera agotado. Cierra el navegador y vuelve a intentarlo.")
            browser.close()
            return

        # Esperar a que la SPA React termine de renderizar
        print("Esperando que la app cargue completamente…")
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except PwTimeout:
            pass  # continuar igualmente si tarda demasiado
        page.wait_for_timeout(2000)  # margen extra por si hay animaciones

        # Obtener folder_id de la API de configuración
        folder_id = ""
        try:
            resp_folder = page.evaluate("""async () => {
                const r = await fetch('/api/v1/setting/medias_folder');
                return await r.json();
            }""")
            folder_id = (resp_folder or {}).get("data", {}).get("id", "")
            if folder_id:
                print(f"Folder ID del media manager: {folder_id}")
        except Exception:
            pass

        print("Media manager listo. Comenzando subida…\n")
        upload_endpoint = UPLOAD_ENDPOINT
        print(f"Endpoint: {upload_endpoint}\n")
        for nombre in imagenes:
            ruta_local = os.path.join(img_dir, nombre)
            nombre_base = os.path.splitext(nombre)[0]

            print(f"  ↑ {nombre}")
            red_log.clear()
            imgs_antes = set(page.evaluate(
                "() => Array.from(document.querySelectorAll('img[src]')).map(i=>i.src)"
                ".filter(s=>s.startsWith('http'))"
            ))

            url_remota = None

            # ── Estrategia 1: fetch desde el navegador (usa sesión completa) ──
            if upload_endpoint:
                try:
                    import base64
                    ext = os.path.splitext(nombre)[1].lstrip(".").lower() or "png"
                    mime = f"image/{ext}"
                    with open(ruta_local, "rb") as f:
                        file_b64 = base64.b64encode(f.read()).decode()

                    result = page.evaluate("""async ([b64, fileName, mimeType, folder, endpoint]) => {
                        try {
                            const binaryStr = atob(b64);
                            const bytes = new Uint8Array(binaryStr.length);
                            for (let i = 0; i < binaryStr.length; i++) {
                                bytes[i] = binaryStr.charCodeAt(i);
                            }
                            const blob = new Blob([bytes], {type: mimeType});
                            const file = new File([blob], fileName, {type: mimeType});
                            const formData = new FormData();
                            formData.append('file', file);
                            if (folder) formData.append('folder', folder);
                            const resp = await fetch(endpoint, {method: 'POST', body: formData});
                            const data = await resp.json();
                            return {status: resp.status, data};
                        } catch(e) {
                            return {status: 0, error: e.toString()};
                        }
                    }""", [file_b64, nombre, mime, folder_id, upload_endpoint])

                    if result and result.get("status") in (200, 201):
                        # Imprimir respuesta completa la primera vez
                        if not mapping:
                            print(f"    [fetch] Respuesta: {result['data']}")
                        url_remota = _extraer_url_de_respuesta(result.get("data"))
                    elif result:
                        print(f"    [fetch] Error {result.get('status')}: {result.get('error') or result.get('data')}")
                except Exception as e:
                    print(f"    [fetch] Excepción: {e}")

            # ── Estrategia 2: file chooser en el navegador ────────────────────
            if not url_remota:
                subida_ok = _intentar_subir(page, ruta_local)
                if not subida_ok:
                    print("    ⚠ No se encontró botón. Sube manualmente y pulsa ENTER.")
                    input("    [ENTER para continuar] ")

                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except PwTimeout:
                    pass
                page.wait_for_timeout(1500)

                for entry in red_log:
                    if entry.get("resp") and entry["resp"].get("data"):
                        url_remota = _extraer_url_de_respuesta(entry["resp"]["data"])
                        if url_remota:
                            break

                if not url_remota:
                    imgs_despues = set(page.evaluate(
                        "() => Array.from(document.querySelectorAll('img[src]')).map(i=>i.src)"
                        ".filter(s=>s.startsWith('http'))"
                    ))
                    nuevas = imgs_despues - imgs_antes
                    if nuevas:
                        url_remota = next(iter(nuevas))

            if url_remota:
                # Extraer id para construir la URL fileLink del portal
                img_id = ""
                if result and isinstance(result.get("data"), dict):
                    inner = result["data"].get("data", {})
                    if isinstance(inner, dict):
                        img_id = inner.get("id", "")
                file_link = f"{BASE_URL}/api/v1/sources/{img_id}/fileLink" if img_id else ""
                mapping[nombre_base] = {"url": url_remota, "id": img_id, "fileLink": file_link}
                print(f"    ✓ URL: {url_remota}")
                if file_link:
                    print(f"    ✓ fileLink: {file_link}")
            else:
                print("    ── Log de red ──")
                for e in red_log:
                    if "inditex.com" in e["req_url"]:
                        print(f"      {e['method']} {e['req_url'][:90]}")
                        if e.get("resp"):
                            print(f"        → {e['resp']['status']}  {str(e['resp']['data'])[:80]}")
                print("    ───────────────")
                url_manual = input("    Pega la URL (o ENTER para saltar): ").strip()
                if url_manual:
                    mapping[nombre_base] = url_manual
                else:
                    print("    Saltada.")

        browser.close()

    # ── Guardar mapping ───────────────────────────────────────────────────────
    if not mapping:
        print("\nNo se capturó ninguna URL. El HTML no se ha modificado.")
        return

    mapping_path = os.path.join(config.OUTPUT_DIR, "imagenes_subidas.json")
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"\nMapping guardado en: {mapping_path}")

    # ── Actualizar HTML ───────────────────────────────────────────────────────
    print("\nActualizando HTML…")
    actualizar_html_con_urls(mapping)
    print("\n¡Listo! Abre output/pagina_styled.html para comprobar el resultado.")


if __name__ == "__main__":
    subir_imagenes()
