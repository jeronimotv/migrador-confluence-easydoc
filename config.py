ORIGEN_URL = "https://confluence.inditex.com/confluence/spaces/AUTSISTALMACEN/pages/494621436/Alta+de+nuevos+consumibles"

#ORIGEN_URL = "https://confluence.inditex.com/confluence/spaces/AUTSISTALMACEN/pages/689669038/Asociar+localizaciones+a+un+centro+de+distribuci%C3%B3n"

INPUT_DIR = "input"

DOWNLOAD_DIR = r"C:\Users\A109820187\OneDrive - Deutsche Telekom AG\Dokumente\migracion_sga\descargas"

OUTPUT_DIR = "output"

# ── SharePoint ────────────────────────────────────────────────────────────────
# Sitio destino donde se subirán los adjuntos
SHAREPOINT_SITE = "https://inditex.sharepoint.com/sites/logistics-docs"

# Carpeta dentro de la biblioteca "Documentos" donde se guardarán los ficheros
SHAREPOINT_FOLDER = "Adjuntos-Confluence"

# Client ID de la app registrada en Azure AD (tipo "Public client / mobile & desktop")
# Pasos rápidos para obtenerlo:
#   1. portal.azure.com → Azure Active Directory → Registros de aplicaciones → Nueva
#   2. Tipo de cuenta: "Solo esta organización"
#   3. URI de redireccionamiento: "Public client/native" → http://localhost
#   4. En "Autenticación" activa "Flujos de dispositivo"
#   5. Copia aquí el "Id. de aplicación (cliente)"
SHAREPOINT_CLIENT_ID = ""  # ← rellenar


