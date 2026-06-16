from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
from datetime import datetime
import requests
import sys
import os
import config

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests
import os
import config

def mejorar_estilos(html):
    soup = BeautifulSoup(html, "html.parser")

    # mejorar títulos H1
    for h1 in soup.find_all("h1"):
        h1['style'] = "font-size:28px;font-weight:bold;margin-bottom:10px;"

    # mejorar títulos H2
    for h2 in soup.find_all("h2"):
        h2['style'] = "font-size:22px;font-weight:bold;margin-top:20px;"

    # mejorar títulos H3
    for h3 in soup.find_all("h3"):
        h3['style'] = "font-size:18px;font-weight:bold;margin-top:15px;"

    return str(soup)

os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
os.makedirs(config.OUTPUT_DIR, exist_ok=True)

def extraer_contenido_principal(html, base_url=""):
    soup = BeautifulSoup(html, "html.parser")

    # 1. eliminar ruido típico
    for tag in soup(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()

    # eliminar tabla de contenidos de Confluence (toc-macro)
    for tag in soup.find_all(class_="toc-macro"):
        tag.decompose()

    # 2. reemplazar src de imágenes por rutas locales;
    #    marcar las que no tienen extensión de imagen (previsualizaciones de adjuntos Confluence)
    extensiones_imagen = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src:
            nombre_img = src.split("?")[0].split("/")[-1]
            ext = os.path.splitext(nombre_img)[1].lower()
            if ext in extensiones_imagen:
                img["src"] = f"images/{nombre_img}"
            else:
                # previsualización de adjunto → usar data-linked-resource-default-alias si existe
                alias = (img.get("data-linked-resource-default-alias")
                         or img.get("data-image-src", "").split("?")[0].split("/")[-1]
                         or nombre_img)
                img["data-adjunto-preview"] = "true"
                img["alt"] = alias

    # 3. convertir bloques de código Confluence (<code style="white-space:pre">) a
    #    <pre><code class="language-xxx"> con texto plano, para que el CSS del portal
    #    destino aplique su estilo de fondo gris correctamente
    for code in soup.find_all("code", style=lambda s: s and "white-space" in s):
        texto_plano = code.get_text("")
        lang = " ".join(c for c in (code.get("class") or []) if c.startswith("language-"))
        nuevo = soup.new_tag("pre")
        inner = soup.new_tag("code", attrs={"class": lang} if lang else {})
        inner.string = texto_plano
        nuevo.append(inner)
        code.replace_with(nuevo)

    # 4. recorrer en orden real del documento con walk recursivo para
    #    tratar tablas como bloques atómicos (no recursar en sus hijos)
    bloques_validos = []

    def _limpiar_tabla(tabla):
        """Limpia atributos Confluence, aplica bordes y pone la primera fila en negrita."""
        attrs_borrar = [
            "data-table-width", "data-layout", "data-local-id",
            "ac:name", "data-macro-name", "data-hasbody",
        ]
        for nodo in tabla.find_all(True):
            for attr in attrs_borrar:
                nodo.attrs.pop(attr, None)
            if "class" in nodo.attrs:
                nodo.attrs.pop("class")

        # Estilo de la tabla: bordes colapsados
        tabla["style"] = "border-collapse:collapse;width:100%;"

        # Bordes en todas las celdas
        for celda in tabla.find_all(["td", "th"]):
            celda["style"] = "border:1px solid #ccc;padding:6px 10px;vertical-align:top;"

        # Primera fila en negrita
        primera_fila = tabla.find("tr")
        if primera_fila:
            for celda in primera_fila.find_all(["td", "th"]):
                celda["style"] = "border:1px solid #ccc;padding:6px 10px;vertical-align:top;font-weight:bold;background-color:#f5f5f5;"

        return tabla

    def _walk(node):
        if not hasattr(node, "name") or node.name is None:
            return
        if node.name == "table":
            _limpiar_tabla(node)
            bloques_validos.append(str(node))
            return  # no recursionar en hijos de la tabla
        if node.name == "img":
            if node.get("data-adjunto-preview"):
                nombre_adj = node.get("alt", "adjunto")
                bloques_validos.append(
                    f'<p><em>(Fichero adjunto: {nombre_adj})</em></p>'
                )
            else:
                src = node.get("src", "")
                nombre_base = os.path.splitext(os.path.basename(src))[0]
                bloques_validos.append(f'<p>[aquí va {nombre_base}]</p>\n<br>')
            return
        if node.name in ["h1", "h2", "h3", "p", "li", "pre"]:
            # Si el nodo contiene imágenes, recursar para extraerlas sin viñeta ni wrapper
            if node.find("img"):
                for child in node.children:
                    _walk(child)
                return
            texto = node.get_text(" ", strip=True)
            if texto and len(texto) > 20:
                bloques_validos.append(str(node))
            return  # no recursionar en hijos (el str(node) ya los incluye)
        for child in node.children:
            _walk(child)

    for child in soup.children:
        _walk(child)

    # 5. reconstruir documento en orden
    return "\n".join(bloques_validos)




def leer_origen():
    import shutil

    origen = os.path.join(config.INPUT_DIR, "origen.html")
    if not os.path.exists(origen):
        print(f"ERROR: No se encuentra '{origen}'.")
        print("Por favor, guarda la página Confluence como HTML en input/origen.html y vuelve a ejecutar.")
        sys.exit(1)

    print(f"Leyendo: {origen}")
    with open(origen, "r", encoding="utf-8") as f:
        html = f.read()

    # intentar extraer solo #main-content si existe en el HTML guardado
    _soup = BeautifulSoup(html, "html.parser")
    main_content = _soup.find(id="main-content")
    if main_content:
        html = str(main_content)

    # limpiar carpeta images
    img_dir = os.path.join(config.OUTPUT_DIR, "images")
    if os.path.exists(img_dir):
        for f in os.listdir(img_dir):
            os.remove(os.path.join(img_dir, f))
    os.makedirs(img_dir, exist_ok=True)

    soup_temp = BeautifulSoup(html, "html.parser")
    img_counter = 1
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    origen_dir = os.path.dirname(os.path.abspath(origen))

    for img in soup_temp.find_all("img"):
        src = img.get("src", "")
        if not src:
            continue
        ext = os.path.splitext(src.split("?")[0])[1].lower() or ".png"
        nuevo_nombre = f"imagen{img_counter}{ts}{ext}"
        ruta_local = os.path.join(img_dir, nuevo_nombre)
        src_limpio = src.split("?")[0]
        if not src_limpio.startswith("http") and not src_limpio.startswith("//"):
            ruta_src = src_limpio.replace("file:///", "").replace("file://", "")
            if not os.path.isabs(ruta_src):
                ruta_src = os.path.join(origen_dir, ruta_src)
            try:
                shutil.copy2(ruta_src, ruta_local)
                print(f"Imagen copiada: {nuevo_nombre}")
            except Exception as e:
                print(f"No se pudo copiar imagen ({src}): {e}")
        else:
            print(f"Imagen remota (sin sesión), placeholder: {nuevo_nombre}")
        img["src"] = f"images/{nuevo_nombre}"
        img_counter += 1

    return str(soup_temp), []


def detectar_adjuntos(html, base_url):

    soup = BeautifulSoup(html, "html.parser")

    adjuntos = []

    extensiones = [
        ".pdf",
        ".sql",
        ".docx",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
        ".zip",
        ".7z",
        ".msg"
    ]

    for enlace in soup.find_all("a", href=True):

        href = enlace["href"]

        if any(
            href.lower().endswith(ext)
            for ext in extensiones
        ):

            url_completa = urljoin(
                base_url,
                href
            )

            adjuntos.append({
                "texto": enlace.get_text(strip=True),
                "url": url_completa
            })

    return adjuntos


def descargar_adjuntos(adjuntos):

    session = requests.Session()

    for adj in adjuntos:

        nombre = adj["url"].split("/")[-1]

        ruta = os.path.join(
            config.DOWNLOAD_DIR,
            nombre
        )

        print(f"Descargando: {nombre}")

        r = session.get(adj["url"])

        with open(ruta, "wb") as f:
            f.write(r.content)

        print(f"Guardado en: {ruta}")


def guardar_html(html, adjuntos=None):

    ruta = os.path.join(config.OUTPUT_DIR, "pagina.html")

    with open(ruta, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML guardado en: {ruta}")


def main():

    html, adjuntos = leer_origen()

    contenido = extraer_contenido_principal(html)

    html_final = mejorar_estilos(contenido)

    guardar_html(html_final, adjuntos)

    print(f"Adjuntos descargados: {len(adjuntos)}")
    for adj in adjuntos:
        print(f"  - {adj['nombre']} → {adj['ruta_local']}")

    print(f"\n¡Listo! Resultado en: {config.OUTPUT_DIR}/pagina.html")


if __name__ == "__main__":
    main()