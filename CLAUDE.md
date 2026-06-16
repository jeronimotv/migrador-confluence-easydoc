# Instrucciones para el agente

## Comando de migración

Cuando el usuario escriba:

```
migrar url
```

Antes de ejecutar nada, comprobar que existen `input/origen.html` e `input/destino.html`.
Si alguno falta, avisar al usuario y detenerse.

Si ambos ficheros existen, ejecutar los cuatro pasos seguidos sin preguntar ni esperar confirmación:

```bash
python main.py
python adaptar_estilos.py
python subir_imagenes.py
python pegar_en_editor.py
```

Ejemplo:

```
migrar url
```

→ ejecuta en secuencia:

```bash
python main.py
python adaptar_estilos.py
python subir_imagenes.py
python pegar_en_editor.py
```

---

## Flujo completo de migración

**Requisito previo:** colocar manualmente en la carpeta `input/`:
- `origen.html` — página Confluence guardada como HTML desde el navegador
- `destino.html` — página del portal destino guardada como HTML desde el navegador

1. **Procesar página origen** (lee `input/origen.html`, sin navegador):
   ```bash
   python main.py
   ```
   Genera `output/pagina.html`, imágenes en `output/images/` y adjuntos en `output/adjuntos/`.

2. **Aplicar estilos del portal destino** (lee `input/destino.html`, sin navegador):
   ```bash
   python adaptar_estilos.py
   ```
   Genera `output/pagina_styled.html` y lo abre automáticamente en el navegador.

---

## Configuración (`config.py`)

| Variable              | Descripción                                         |
|-----------------------|-----------------------------------------------------|
| `ORIGEN_URL`          | URL por defecto si no se pasa argumento a main.py   |
| `OUTPUT_DIR`          | Carpeta de salida (por defecto `output/`)           |
| `DOWNLOAD_DIR`        | Carpeta de descargas locales                        |
| `SHAREPOINT_SITE`     | URL del sitio SharePoint destino                    |
| `SHAREPOINT_FOLDER`   | Carpeta dentro de SharePoint para los adjuntos      |
| `SHAREPOINT_CLIENT_ID`| Client ID de la app Azure AD para autenticación     |
