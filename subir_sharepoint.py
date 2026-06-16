"""
subir_sharepoint.py
-------------------
Sube los adjuntos descargados en output/adjuntos/ a SharePoint y actualiza
los enlaces en output/pagina.html con las URLs reales de SharePoint.

Requisitos:
  - pip install msal
  - Rellenar SHAREPOINT_CLIENT_ID en config.py  (ver instrucciones dentro del fichero)

Ejecución:
  python subir_sharepoint.py
"""

import os
import json
import requests
import msal
from bs4 import BeautifulSoup
import config

# ── Constantes ────────────────────────────────────────────────────────────────

SCOPES = ["https://graph.microsoft.com/Files.ReadWrite.All",
          "https://graph.microsoft.com/Sites.ReadWrite.All"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def descubrir_tenant_id(sharepoint_site: str) -> str:
    """Obtiene el Tenant ID de Microsoft a partir del dominio de SharePoint."""
    dominio = sharepoint_site.split("/")[2]          # inditex.sharepoint.com
    tenant_dominio = dominio.replace(".sharepoint.com", ".onmicrosoft.com")
    url = f"https://login.microsoftonline.com/{tenant_dominio}/.well-known/openid-configuration"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    token_endpoint = resp.json()["token_endpoint"]   # https://login.../TENANT_ID/oauth2/...
    tenant_id = token_endpoint.split("/")[3]
    print(f"Tenant ID descubierto: {tenant_id}")
    return tenant_id


def obtener_token(tenant_id: str, client_id: str) -> str:
    """Abre el navegador para login interactivo (SSO corporativo compatible)."""
    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}"
    )

    # Intentar primero con caché (evita re-login si ya se autenticó antes)
    cuentas = app.get_accounts()
    if cuentas:
        result = app.acquire_token_silent(SCOPES, account=cuentas[0])
        if result and "access_token" in result:
            print("Token obtenido desde caché.")
            return result["access_token"]

    # Login interactivo — abre ventana del navegador con SSO corporativo
    print("Abriendo navegador para autenticación en Microsoft 365...")
    result = app.acquire_token_interactive(scopes=SCOPES)

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "desconocido"))
        raise RuntimeError(f"Error de autenticación: {error}")

    return result["access_token"]


def obtener_site_id(token: str, sharepoint_site: str) -> str:
    """Obtiene el ID del sitio de SharePoint via Graph API."""
    dominio = sharepoint_site.split("/")[2]
    ruta    = "/" + "/".join(sharepoint_site.split("/")[3:])   # /sites/logistics-docs
    url = f"https://graph.microsoft.com/v1.0/sites/{dominio}:{ruta}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    resp.raise_for_status()
    site_id = resp.json()["id"]
    print(f"Site ID: {site_id}")
    return site_id


def subir_fichero(token: str, site_id: str, carpeta: str, ruta_local: str) -> str:
    """
    Sube un fichero a SharePoint (sobreescribe si ya existe).
    Devuelve la webUrl del fichero subido.
    Usa la API de carga simple (< 4 MB). Para ficheros mayores habría que
    usar sesiones de carga fragmentada, pero para adjuntos de Confluence es suficiente.
    """
    nombre_fichero = os.path.basename(ruta_local)
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}"
        f"/drive/root:/{carpeta}/{nombre_fichero}:/content"
    )
    with open(ruta_local, "rb") as f:
        contenido = f.read()

    resp = requests.put(
        url,
        data=contenido,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream"
        },
        timeout=60
    )
    resp.raise_for_status()
    web_url = resp.json().get("webUrl", "")
    print(f"  Subido: {nombre_fichero} → {web_url}")
    return web_url


def actualizar_links_html(ruta_html: str, mapa_urls: dict) -> None:
    """
    Reemplaza en pagina.html los enlaces locales 'adjuntos/nombre.ext'
    por las URLs reales de SharePoint.
    mapa_urls = { "nombre.pdf": "https://sharepoint.com/.../nombre.pdf", ... }
    """
    with open(ruta_html, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    for enlace in soup.find_all("a", href=True):
        href = enlace["href"]
        # coincide con links locales del tipo adjuntos/fichero.ext
        if href.startswith("adjuntos/"):
            nombre = href.split("/")[-1]
            if nombre in mapa_urls:
                enlace["href"] = mapa_urls[nombre]

    with open(ruta_html, "w", encoding="utf-8") as f:
        f.write(str(soup))

    print(f"Links actualizados en: {ruta_html}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not config.SHAREPOINT_CLIENT_ID:
        print(
            "ERROR: SHAREPOINT_CLIENT_ID está vacío en config.py\n"
            "Sigue los pasos indicados en los comentarios de config.py para obtenerlo."
        )
        return

    # 1. Listar adjuntos disponibles
    adj_dir = os.path.join(config.OUTPUT_DIR, "adjuntos")
    if not os.path.isdir(adj_dir):
        print(f"No se encontró la carpeta {adj_dir}. Ejecuta primero main.py.")
        return

    ficheros = [f for f in os.listdir(adj_dir) if os.path.isfile(os.path.join(adj_dir, f))]
    if not ficheros:
        print("No hay adjuntos para subir.")
        return

    print(f"Adjuntos a subir ({len(ficheros)}):")
    for f in ficheros:
        print(f"  - {f}")

    # 2. Autenticación
    tenant_id = descubrir_tenant_id(config.SHAREPOINT_SITE)
    token     = obtener_token(tenant_id, config.SHAREPOINT_CLIENT_ID)
    site_id   = obtener_site_id(token, config.SHAREPOINT_SITE)

    # 3. Subir ficheros
    mapa_urls = {}
    for nombre in ficheros:
        ruta_local = os.path.join(adj_dir, nombre)
        web_url = subir_fichero(token, site_id, config.SHAREPOINT_FOLDER, ruta_local)
        mapa_urls[nombre] = web_url

    # 4. Actualizar pagina.html y pagina_styled.html con las URLs reales
    for nombre_html in ["pagina.html", "pagina_styled.html"]:
        ruta_html = os.path.join(config.OUTPUT_DIR, nombre_html)
        if os.path.isfile(ruta_html):
            actualizar_links_html(ruta_html, mapa_urls)

    # 5. Guardar mapa de URLs para referencia futura
    ruta_mapa = os.path.join(config.OUTPUT_DIR, "adjuntos_sharepoint.json")
    with open(ruta_mapa, "w", encoding="utf-8") as f:
        json.dump(mapa_urls, f, ensure_ascii=False, indent=2)
    print(f"Mapa de URLs guardado en: {ruta_mapa}")

    print("\n¡Listo! Todos los adjuntos están en SharePoint y los enlaces en pagina.html actualizados.")


if __name__ == "__main__":
    main()
