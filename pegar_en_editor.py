"""
pegar_en_editor.py
------------------
Pega el contenido de output/pagina_styled.html en el editor del portal.
Texto e imágenes se insertan correctamente usando el API nativo de TipTap.

Ejecución:
  python pegar_en_editor.py
"""

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from bs4 import BeautifulSoup
import os
import config

EDITOR_URL = "https://soluciones.docs.inditex.com/admin/documents/editor/add"
BASE_URL   = "https://soluciones.docs.inditex.com"
AUTH_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.json")


def extraer_contenido(ruta_html: str) -> tuple[str, str]:
    with open(ruta_html, "r", encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    titulo = (soup.find("title") or soup.new_tag("t")).get_text(strip=True) or "Documento migrado"
    contenedor = soup.find("div", class_="container")
    contenido = contenedor.decode_contents() if contenedor else (
        soup.body.decode_contents() if soup.body else html
    )
    return titulo, contenido


def obtener_fuentes(page) -> dict:
    try:
        sources = page.evaluate("""async () => {
            let all = [], p = 1, pages = 1;
            while (p <= pages) {
                const r = await fetch(
                    `/api/v1/admin/sources?folder=image&fileTypeId=1&isPublic=true&page=${p}&pageSize=50`
                );
                const d = await r.json();
                if (Array.isArray(d.data)) all = all.concat(d.data);
                pages = d.metadata?.pages_total || 1;
                p++;
            }
            return all;
        }""")
        mapping = {}
        for s in (sources or []):
            nombre = s.get("name", "")
            if nombre:
                mapping[nombre] = {
                    "id":  s.get("id", ""),
                    "url": s.get("staticPublicUrl", ""),
                    "ref": s.get("mdSourceReference", ""),
                }
        print(f"  {len(mapping)} imagen(es) en el media manager.")
        return mapping
    except Exception as e:
        print(f"  Aviso: {e}")
        return {}


def preparar_html(contenido: str, fuentes: dict) -> tuple[str, list]:
    soup = BeautifulSoup(contenido, "html.parser")
    imagenes = []
    for idx, img in enumerate(soup.find_all("img")):
        alt = img.get("alt", "")
        src = img.get("src", "")          # ruta local o URL puesta por subir_imagenes.py
        nombre_base = os.path.splitext(alt)[0] if alt else ""
        src_base = os.path.splitext(os.path.basename(src))[0] if src else ""
        # Buscar primero por alt, luego por nombre de fichero (src_base)
        info = next(
            (v for k, v in fuentes.items()
             if nombre_base and (nombre_base in k or k.startswith(nombre_base))),
            None
        )
        if not info and src_base:
            info = next(
                (v for k, v in fuentes.items()
                 if src_base in k or k.startswith(src_base)),
                None
            )
        # Fallback: usar la src del propio <img> si el API no la devolvió
        if not info and src.startswith("http"):
            info = {"url": src, "id": "", "ref": ""}
        placeholder = f"IMGPH{idx}IMGPH"
        span = soup.new_tag("span")
        span.string = placeholder
        img.replace_with(span)
        imagenes.append({"placeholder": placeholder, "alt": alt, "src_base": src_base, "info": info})
    return str(soup), imagenes


def _posicionar_cursor(page, placeholder: str) -> bool:
    """Localiza el nodo de texto, hace scroll al viewport y triple-click."""
    coords = page.evaluate("""([ph]) => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let n;
        while ((n = walker.nextNode())) {
            if (n.textContent.trim() === ph) {
                const el = n.parentElement;
                el.scrollIntoView({block: 'center', behavior: 'instant'});
                const rect = el.getBoundingClientRect();
                return {found: true, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2,
                        tag: el.tagName, w: rect.width, h: rect.height};
            }
        }
        return {found: false};
    }""", [placeholder])

    if not coords.get("found"):
        print(f"    [cursor-debug] '{placeholder}' no encontrado en DOM")
        return False

    page.wait_for_timeout(150)
    page.mouse.click(coords["x"], coords["y"], click_count=3)  # selecciona todo el párrafo
    page.wait_for_timeout(300)
    return True


def _encontrar_editor_tiptap(page) -> str:
    """Recorre el árbol de componentes Vue 3 buscando la instancia TipTap.
    Devuelve el nombre de la variable global window.__tiptap_editor__ si tiene éxito,
    o una cadena de error."""
    return page.evaluate("""() => {
        function walk(vnode, depth) {
            if (!vnode || depth > 250) return null;
            const c = vnode.component;
            if (c) {
                const ss = c.setupState;
                if (ss && typeof ss === 'object') {
                    try {
                        const ssKeys = [...Reflect.ownKeys(ss)].filter(k => typeof k === 'string');
                        for (const k of ssKeys) {
                            try {
                                let v = ss[k];
                                // Deswrapear Vue ref
                                if (v && typeof v === 'object' && v.__v_isRef) v = v.value;
                                if (v && typeof v === 'object'
                                    && typeof v.chain === 'function'
                                    && v.commands && v.schema) {
                                    return v;
                                }
                            } catch(e) {}
                        }
                    } catch(e) {}
                }
                if (c.subTree) {
                    const r = walk(c.subTree, depth + 1);
                    if (r) return r;
                }
            }
            if (Array.isArray(vnode.children)) {
                for (const child of vnode.children) {
                    if (child && typeof child === 'object') {
                        const r = walk(child, depth + 1);
                        if (r) return r;
                    }
                }
            }
            return null;
        }

        const app = document.getElementById('app').__vue_app__;
        const rootVnode = app._container?._vnode;
        if (!rootVnode) return 'no-root-vnode';

        const editor = walk(rootVnode, 0);
        if (!editor) return 'editor-not-found';

        // Guardar referencia global para reutilizar
        window.__tiptap_editor__ = editor;

        // Devolver los tipos de nodo disponibles para diagnóstico
        const nodeTypes = Object.keys(editor.schema?.nodes || {});
        return 'found:' + nodeTypes.join(',');
    }""")


def insertar_imagenes_via_tiptap(page, imagenes: list):
    """Inserta cada imagen via TipTap API (tree-walk Vue 3) con fallback a clipboard."""

    # ── Buscar editor TipTap una sola vez ─────────────────────────────────────
    editor_info = _encontrar_editor_tiptap(page)
    print(f"  [tiptap] {editor_info[:200]}")

    # Detectar el nombre del nodo imagen en el schema
    img_node_type = None
    if editor_info.startswith("found:"):
        node_types = editor_info[6:].split(",")
        for t in node_types:
            if "image" in t.lower() or "img" in t.lower():
                img_node_type = t
                break
    print(f"  [tiptap] tipo nodo imagen: {img_node_type}")

    for idx, item in enumerate(imagenes):
        ph   = item["placeholder"]
        alt  = item["alt"]
        info = item.get("info")

        # ── 1. Posicionar cursor en el placeholder ────────────────────────────
        ok = _posicionar_cursor(page, ph)
        if not ok:
            print(f"  ⚠ '{ph}' no encontrado en doc")
            continue

        url = (info or {}).get("url", "")
        img_id = (info or {}).get("id", "") or url
        if not url:
            print(f"  ⚠ Sin URL para '{alt}' — omitiendo")
            continue

        # ── 2a. Insertar via TipTap API si encontramos el editor ─────────────
        result = "skip"
        if img_node_type and editor_info.startswith("found:"):
            result = page.evaluate("""([nodeType, url, alt]) => {
                const editor = window.__tiptap_editor__;
                if (!editor) return 'no-ref';
                try {
                    editor.chain()
                        .focus()
                        .deleteSelection()
                        .insertContent({ type: nodeType, attrs: { src: url } })
                        .run();
                    return 'api-ok:' + nodeType;
                } catch(e) {
                    return 'api-err:' + e.message;
                }
            }""", [img_node_type, img_id, alt])

        # ── 2b. Fallback: ClipboardEvent con varios formatos HTML ─────────────
        # edc-markdown-image usa el ID como src (construye /api/v1/sources/{id}/fileLink)
        # Las variantes <img> usan la URL CDN directamente
        if not result.startswith("api-ok"):
            for tag in [
                f'<edc-markdown-image src="{img_id}" alt="{alt}"></edc-markdown-image>',
                f'<img src="{url}" alt="{alt}" data-type="EdcMarkdownImage">',
                f'<img src="{url}" alt="{alt}">',
            ]:
                r2 = page.evaluate("""([html]) => {
                    const pm = document.querySelector('.ProseMirror');
                    if (!pm) return 'no-pm';
                    pm.focus();
                    const dt = new DataTransfer();
                    dt.setData('text/html', html);
                    dt.setData('text/plain', '');
                    pm.dispatchEvent(new ClipboardEvent('paste',
                        {bubbles:true, cancelable:true, clipboardData:dt}));
                    return 'paste-ok';
                }""", [tag])
                result = r2 + "|" + tag[:40]
                page.wait_for_timeout(600)
                # Comprobar si se insertó algo visible (excluir ProseMirror separators)
                has_img = page.evaluate("""() => {
                    const pm = document.querySelector('.ProseMirror');
                    return pm.querySelector(
                        'img:not(.ProseMirror-separator), [data-type*="image"], [data-type*="Image"]'
                    ) !== null;
                }""")
                if has_img:
                    break

        # Diagnóstico DOM post-insert (solo imagen 0)
        if idx == 0:
            dom_info = page.evaluate("""() => {
                const pm = document.querySelector('.ProseMirror');
                const nodes = [...pm.querySelectorAll(
                    'img:not(.ProseMirror-separator), [data-type], edc-markdown-image'
                )].slice(0, 5).map(el => ({
                    tag: el.tagName,
                    dataType: el.getAttribute('data-type'),
                    src: (el.getAttribute('src') || '').slice(0, 80),
                    visible: el.offsetWidth > 0 && el.offsetHeight > 0,
                    h: el.offsetHeight, w: el.offsetWidth,
                    attrs: [...el.attributes].map(a=>a.name+':'+a.value.slice(0,40)).join(' | ')
                }));
                return nodes;
            }""")
            import json as _jd
            print(f"  [dom-post] {_jd.dumps(dom_info, ensure_ascii=False)[:400]}")

        page.wait_for_timeout(600)
        print(f"  insert [{idx}] {alt}: {result}")

        # ── 3. Limpiar placeholder si quedó en el DOM ─────────────────────────
        for _ in range(2):
            cleaned = page.evaluate("""([ph]) => {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let n;
                while ((n = walker.nextNode())) {
                    if (n.textContent.trim() === ph) {
                        const el = n.parentElement;
                        el.scrollIntoView({block: 'center', behavior: 'instant'});
                        const rect = el.getBoundingClientRect();
                        return {found: true, x: rect.left + rect.width/2, y: rect.top + rect.height/2};
                    }
                }
                return {found: false};
            }""", [ph])
            if cleaned.get("found"):
                page.mouse.click(cleaned["x"], cleaned["y"], click_count=3)
                page.keyboard.press("Delete")
                page.wait_for_timeout(200)
            else:
                break
        print(f"  OK {alt}")




def pegar_en_editor():
    ruta_html = os.path.join(config.OUTPUT_DIR, "pagina_styled.html")
    if not os.path.exists(ruta_html):
        print(f"ERROR: No existe '{ruta_html}'.")
        return

    titulo, contenido = extraer_contenido(ruta_html)
    print(f"Titulo : {titulo}")
    print(f"Tamano : {len(contenido):,} caracteres")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx_opts = {"storage_state": AUTH_FILE} if os.path.exists(AUTH_FILE) else {}
        context = browser.new_context(**ctx_opts)
        page    = context.new_page()

        print("\nAbriendo editor...")
        page.goto(EDITOR_URL, timeout=60_000)

        # ── Comprobar si la sesión guardada es válida (rápido) ────────────────
        sesion_ok = False
        if os.path.exists(AUTH_FILE):
            print("  Sesion guardada encontrada, comprobando...")
            try:
                page.wait_for_url("**/admin/**", timeout=8_000)
                sesion_ok = True
                print("  Sesion reutilizada correctamente (sin login).")
            except PwTimeout:
                print("  Sesion expirada. Autenticate con SSO en el navegador.")

        if not sesion_ok:
            print("-> Autenticate con SSO si se solicita.\n")
            try:
                page.wait_for_url("**/admin/**", timeout=300_000)
            except PwTimeout:
                print("Timeout esperando autenticacion.")
                browser.close()
                return

        # Guardar/actualizar sesión para la próxima ejecución
        context.storage_state(path=AUTH_FILE)
        print(f"  Sesion guardada en auth.json")

        print("Esperando TipTap...")
        try:
            page.wait_for_selector(".ProseMirror", timeout=30_000)
        except PwTimeout:
            print("ERROR: editor no cargo.")
            browser.close()
            return
        page.wait_for_timeout(2000)

        print("Obteniendo imagenes del media manager...")
        fuentes = obtener_fuentes(page)

        html_sin_imgs, imagenes = preparar_html(contenido, fuentes)
        print(f"  {len(imagenes)} imagen(es) marcada(s).")

        # Sustituir enlaces de adjuntos con URLs de SharePoint si disponibles
        import json as _jjsp
        _adj_json = os.path.join(config.OUTPUT_DIR, "adjuntos_sharepoint.json")
        if os.path.exists(_adj_json):
            with open(_adj_json, encoding="utf-8") as _f:
                _adj_map = _jjsp.load(_f)
            if _adj_map:
                from bs4 import BeautifulSoup as _BS
                _soup_adj = _BS(html_sin_imgs, "html.parser")
                _n_adj = 0
                for _a in _soup_adj.find_all("a", href=True):
                    _nombre_adj = _a["href"].split("/")[-1]
                    if _nombre_adj in _adj_map:
                        _a["href"] = _adj_map[_nombre_adj]
                        _n_adj += 1
                if _n_adj:
                    html_sin_imgs = str(_soup_adj)
                    print(f"  {_n_adj} enlace(s) de adjunto sustituido(s) con URL de SharePoint.")

        # Enriquecer info con fileLink de imagenes_subidas.json (src correcto para TipTap)
        import json as _jj
        _json_path = os.path.join(config.OUTPUT_DIR, "imagenes_subidas.json")
        if os.path.exists(_json_path):
            with open(_json_path, encoding="utf-8") as _f:
                _subidas = _jj.load(_f)
            for _img in imagenes:
                _nb = os.path.splitext(_img["alt"])[0] if _img["alt"] else ""
                # Buscar por alt; si no, por src_base (nombre del fichero local)
                _subida = _subidas.get(_nb) or _subidas.get(_img.get("src_base", ""), {})
                if isinstance(_subida, dict) and _subida.get("fileLink"):
                    _cdn_url = _subida.get("url", "")
                    _img_id  = _subida.get("id", "")
                    # Guardar URL CDN (para fallback) e ID (para TipTap API)
                    _img["info"] = {"url": _cdn_url, "id": _img_id, "ref": ""}
                    print(f"  ✓ imagen vinculada: {_img.get('src_base','')} → {_cdn_url[:60]}")

        titulo_ok = False
        for sel in [
            "input[placeholder*='tulo' i]",
            "input[placeholder*='title' i]",
            "input[placeholder*='nombre' i]",
            "input[placeholder*='name' i]",
            "input[name='title']",
            "input[name='titulo']",
            ".document-title input",
            ".title input",
            "header input[type='text']",
        ]:
            campo = page.query_selector(sel)
            if campo and campo.is_visible():
                campo.click()
                campo.fill(titulo)
                print(f"  Titulo introducido: '{titulo}'")
                titulo_ok = True
                break
        if not titulo_ok:
            # Fallback: primer input de texto visible en la página
            for inp in page.query_selector_all("input[type='text'], input:not([type])"):
                if inp.is_visible():
                    inp.click()
                    inp.fill(titulo)
                    print(f"  Titulo introducido (fallback): '{titulo}'")
                    titulo_ok = True
                    break
        if not titulo_ok:
            print(f"  ⚠ No se encontró campo de titulo — introduce manualmente: '{titulo}'")

        print("Insertando texto...")
        # Usar JS focus para evitar que la cabecera sticky intercepte el click físico
        page.evaluate("document.querySelector('.ProseMirror').focus()")
        page.wait_for_timeout(300)

        resultado = page.evaluate("""([html]) => {
            const editor = document.querySelector('.ProseMirror');
            if (!editor) return 'ERROR';
            editor.focus();
            document.execCommand('selectAll', false, null);
            try {
                const dt = new DataTransfer();
                dt.setData('text/html', html);
                dt.setData('text/plain', '');
                const ev = new ClipboardEvent('paste', {bubbles:true, cancelable:true, clipboardData:dt});
                editor.dispatchEvent(ev);
                return 'ok';
            } catch(e) {
                document.execCommand('insertHTML', false, html);
                return 'ok-execCommand';
            }
        }""", [html_sin_imgs])
        print(f"  Paste texto: {resultado}")
        page.wait_for_timeout(2500)

        # ── Diagnóstico post-paste ────────────────────────────────────────────
        diag = page.evaluate("""() => {
            const pm = document.querySelector('.ProseMirror');
            if (!pm) return {error: 'no .ProseMirror'};

            // Contenido de texto del editor
            const txt = pm.innerText?.slice(0, 2000) || '';

            // ¿Está el placeholder en el DOM?
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            const foundPH = [];
            let n;
            while ((n = walker.nextNode())) {
                if (n.textContent.includes('IMGPH0IMGPH')) {
                    foundPH.push({parent: n.parentElement?.tagName, text: n.textContent.slice(0,80)});
                }
            }

            // Estructura de __vue_app__
            const appEl = document.getElementById('app');
            const app   = appEl?.__vue_app__;
            const inst  = app?._instance;
            const vueInfo = {
                appKeys: app  ? Object.keys(app).slice(0, 20) : null,
                hasInst: !!inst,
                instKeys: inst ? Object.keys(inst).slice(0, 25) : null,
                hasProxy: !!inst?.proxy,
                proxyEditor: !!inst?.proxy?.editor,
                hasSubTree: !!inst?.subTree,
                subTreeKeys: inst?.subTree ? Object.keys(inst.subTree).slice(0, 15) : null,
                subTreeCompType: inst?.subTree?.component?.type?.name || null,
            };

            // Buscar claves __vue en la cadena de padres de .ProseMirror
            const chain = [];
            let el = pm;
            while (el && el !== document.body) {
                const vkeys = Object.getOwnPropertyNames(el).filter(k => k.startsWith('__vue'));
                if (vkeys.length) {
                    const entry = {tag: el.tagName, cls: (el.className||'').slice(0,40), vkeys};
                    chain.push(entry);
                }
                el = el.parentElement;
            }

            return {txt, foundPH, vueInfo, chain};
        }""")
        import json as _json
        print(f"  [diag] placeholder_en_DOM={diag.get('foundPH')}")
        print(f"  [diag] vueInfo={_json.dumps(diag.get('vueInfo',{}), ensure_ascii=False)[:600]}")
        print(f"  [diag] chain={_json.dumps(diag.get('chain',[]), ensure_ascii=False)[:200]}")
        # Imprimir el texto completo en trozos
        txt_full = diag.get('txt', '')
        print(f"  [diag] editor_txt ({len(txt_full)} chars): {txt_full[:400]}")


        if imagenes:
            print("Insertando imagenes...")
            insertar_imagenes_via_tiptap(page, imagenes)

        page.wait_for_timeout(1000)
        preview = os.path.join(config.OUTPUT_DIR, "editor_preview.png")
        page.screenshot(path=preview)
        print(f"\nScreenshot: {preview}")
        print("\nListo. Pulsa PUBLISH o SAVE DRAFT en el navegador.")
        input("\n[ENTER para cerrar] ")
        browser.close()


if __name__ == "__main__":
    pegar_en_editor()
