from bs4 import BeautifulSoup
import os
import sys
import config

DESTINO_HTML = os.path.join(config.INPUT_DIR, "destino.html")
ORIGEN_HTML = os.path.join(config.OUTPUT_DIR, "pagina.html")
SALIDA_HTML = os.path.join(config.OUTPUT_DIR, "pagina_styled.html")


def leer_destino():
    if not os.path.exists(DESTINO_HTML):
        print(f"ERROR: No se encuentra '{DESTINO_HTML}'.")
        print("Por favor, guarda la página destino como HTML en input/destino.html y vuelve a ejecutar.")
        sys.exit(1)
    print(f"Leyendo estilos de: {DESTINO_HTML}")
    with open(DESTINO_HTML, "r", encoding="utf-8") as f:
        return f.read()


def extraer_css(html_destino, base_url):
    soup = BeautifulSoup(html_destino, "html.parser")

    bloques_css = []

    # hojas de estilo externas
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href", "")
        if href:
            if not href.startswith("http"):
                from urllib.parse import urljoin
                href = urljoin(base_url, href)
            bloques_css.append(f'<link rel="stylesheet" href="{href}">')

    # estilos inline
    for style in soup.find_all("style"):
        bloques_css.append(str(style))

    # clases del body (tema, modo claro/oscuro, etc.)
    body = soup.find("body")
    body_class = body.get("class", []) if body else []
    body_class_str = " ".join(body_class)

    return "\n".join(bloques_css), body_class_str


def numerar_titulos(contenido_html):
    soup = BeautifulSoup(contenido_html, "html.parser")
    c1 = c2 = c3 = 0  # contadores jerárquicos
    for tag in soup.find_all(["h1", "h2", "h3"]):
        texto_original = tag.get_text(" ", strip=True)
        # eliminar botones internos (copy-heading-link)
        for btn in tag.find_all(["button", "span"], class_=lambda c: c and "copy-heading" in c):
            btn.decompose()
        tag.clear()
        if tag.name == "h1":
            c1 += 1; c2 = 0; c3 = 0
            tag.string = f"{c1}. {texto_original}"
        elif tag.name == "h2":
            c2 += 1; c3 = 0
            tag.string = f"{c1}.{c2} {texto_original}"
        else:  # h3
            c3 += 1
            tag.string = f"{c1}.{c2}.{c3} {texto_original}"
    return str(soup)


def generar_pagina_styled(css_html, body_class, contenido_html, titulo="Documento migrado"):
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{titulo}</title>
  {css_html}
</head>
<body class="{body_class}">
  <div class="container markdown" style="max-width:860px;margin:40px auto;padding:0 24px;">
    {contenido_html}
  </div>
</body>
</html>"""


def extraer_titulo_origen():
    origen = os.path.join(config.INPUT_DIR, "origen.html")
    with open(origen, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    raw = (soup.find("title") or soup.new_tag("t")).get_text(strip=True)
    # quitar el sufijo " - ... - Confluence" típico de Confluence
    partes = raw.split(" - ")
    return partes[0].strip() if partes else raw


def main():
    # leer contenido ya generado
    with open(ORIGEN_HTML, "r", encoding="utf-8") as f:
        contenido = f.read()

    # leer estilos de la página destino local
    html_destino = leer_destino()

    css_html, body_class = extraer_css(html_destino, "")

    titulo = extraer_titulo_origen()

    contenido_numerado = numerar_titulos(contenido)

    html_final = generar_pagina_styled(css_html, body_class, contenido_numerado, titulo)

    with open(SALIDA_HTML, "w", encoding="utf-8") as f:
        f.write(html_final)

    print(f"Página estilizada guardada en: {SALIDA_HTML}")

    import webbrowser
    webbrowser.open(os.path.abspath(SALIDA_HTML))


if __name__ == "__main__":
    main()
