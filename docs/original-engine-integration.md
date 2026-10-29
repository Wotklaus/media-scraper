# Restauración e integración del motor original

## Restauración completada antes de integrar

- Raíz: `media-scraper`, rama `feature/setup-inicial`.
- Commit restaurado: `15520737842a72361d423ec960bde6ebdebccf63` (`1552073`).
- Se ejecutaron `git reset --hard HEAD`, `git clean -nd` y `git clean -fd`.
- Se verificó `git status --short` vacío **antes** de comenzar la integración.
- Todos los cambios de las revisiones anteriores sin commit fueron descartados.
- No se usó `git clean -fdx`. `.venv`, `backend/.env` y el perfil privado de
  Chromium siguen ignorados y se conservaron.
- No hubo cambio de rama, pull, commit, push ni modificaciones en GitHub.

Los cambios que ahora aparecen en el árbol de trabajo son esta integración nueva.

## Procedencia, licencia y auditoría

Se clonó `https://github.com/Jccasav14/SCRAPINGTIKTOK` en
`/tmp/media-scrapingtiktok-original`. Commit de referencia:
`7deb6d0189f8b05d2f4e7d4ea7292b616258c205`.

- Copia completa inalterada: `backend/vendor/scrapingtiktok/upstream/tiktok_scraper.py`.
- SHA-256 de esa copia y del archivo clonado:
  `b836bbc154b29a96abc491313ddb1409a1a5240be977c2dc37baef292459ad0a`.
- Módulo ejecutable integrado: `backend/vendor/scrapingtiktok/tiktok_scraper.py`.
- Licencia MIT original con `Copyright (c) 2026 Jccasav`:
  `backend/vendor/scrapingtiktok/LICENSE`.
- **Todas las líneas modificadas** frente al original están en
  `backend/vendor/scrapingtiktok/INTEGRATION.patch`.
- `backend/vendor/scrapingtiktok/PROVENANCE.json` fija hashes de ambos archivos,
  commit, origen y rangos exactos de líneas originales/integradas modificadas.

El ejecutable no es byte a byte idéntico al original: los ajustes de sesión,
privacidad, procedencia y métricas siguientes son explícitos. La copia inalterada
permite comprobarlos sin depender de un repositorio remoto cambiante.

## Funciones originales y modificaciones necesarias

Se conserva la clase `TikTokScraper` y el flujo de `scrape()`,
`_extract_video_urls()`, `_extract_single_video_details()` y sus callbacks anidados
`intercept_user_list()` e `intercept_comments()`: lectura de rehidratación,
scrolls, acumulación, control de estancamiento, clasificación por scene,
interceptores, controles alternativos y respaldo DOM permanecen en el archivo
vendorizado. No delegan la extracción al motor antiguo de Media Scraper.

| Líneas del módulo ejecutable | Cambio y justificación |
| --- | --- |
| Importaciones e inicializador, 17–76 | Se importa la capa de compatibilidad. `_setup_context()` conserva firma y punto de llamada, pero su inicialización efímera se sustituye por Chromium persistente con el bloqueo original. No se carga una cookie de `.env` ni se copian cookies. Se desactiva Stealth y sus flags; no se añade esa dependencia. |
| `scrape()`, desde 79 | Se mantiene la API asíncrona y la secuencia original. `persistent_playwright()` garantiza el cierre y la liberación del bloqueo incluso en errores. |
| `intercept_user_list()`, desde 107 | Host/ruta/HTTP, scene activo y `secUid`/`userId` deben corresponder al perfil verificado. Se rechazan identificadores contradictorios, estados fallidos y usernames ilegibles. El estado 10222 se asocia a su sección; no se fuerza una lista privada. |
| Métricas de perfil, desde 213 | Los campos ausentes/ilegibles son `None`, no cero; se conserva el cero comprobado de `heartCount`. Se mantiene la lectura `statsV2`/`stats` y la corrección de enteros negativos del original. |
| Listas, desde 256 | La sesión persistente sustituye el requisito de una cookie copiada. Los clicks no usan `force`. Se marca scene 67/21 durante la interacción correspondiente y se conserva scroll/acumulación original. |
| `_extract_video_urls()`, desde 378 | Se conserva el descubrimiento, deduplicación y orden por ID originales. Se valida el host y el enlace completo para no aceptar dominios externos que imiten la ruta. El adaptador advierte que ID no prueba cronología completa. |
| `intercept_comments()`, desde 447 | Se conserva el listener previo a `goto`, IDs, campos de autor, texto y métricas. Se exige un único `aweme_id` del video y se descartan contradicciones en sobre/elementos y estados fallidos. Si falta CID, se deduplica por identidad/texto, no por un ID vacío común. |
| Rehidratación del video, desde 546 | Antes de aceptar datos se verifican ID y autoría. `statsV2` puede aportar enteros exactos. Se marca `_verified`; un ID deducido de URL sin JSON verificable no basta para persistir. |
| Controles de comentarios, desde 601 | Se mantienen selectores, scrolls y respaldo alternativo originales. Se elimina la retirada de overlays de login y se usan clicks nativos sin `force`. Las verificaciones/autenticación detienen la extracción. |
| DOM, desde 684 | Se conservan los selectores y la estructura del fallback original. El username procede del enlace público, no del nickname; los nodos deben pertenecer al mismo item y no a un reply anidado. La deduplicación incluye autor/texto. |
| Excepciones y valores por defecto en los rangos de `INTEGRATION.patch` | Las excepciones de acceso/identidad escapan de las capturas genéricas originales. Los mensajes registran el tipo del error y no detalles de URLs o credenciales. Las métricas desconocidas permanecen `None`. |

El archivo original mantiene llamadas `browser.new_context()`; la fachada
`SharedBrowser` les proporciona **leases de páginas sobre un único contexto
persistente**, no nuevos contextos aislados. Cerrar un lease solo cierra sus páginas.
El perfil autorizado y su estado se reutilizan sin leer/copiar cookies manualmente.
Los bloques originales de inyección de cookies restantes son inalcanzables en
esta integración: el constructor establece `session_id=None` y el lease no expone
una API para inyectarlas. `load_env_cookie()` se conserva para auditoría, pero la
aplicación no lo invoca.

## Adaptador y conexión a la aplicación

Ruta de producción:

```text
GET /api/profile/{username}?mode=real
  -> backend.main.get_profile
  -> backend.reference_engine.scrape_profile
  -> asyncio.run(extract_profile)
  -> TikTokScraper.scrape (módulo original integrado)
  -> backend.reference_adapter.adapt_profile
  -> save_profile -> normalize_profile -> ProfileRepository.save -> Atlas/historial
```

El endpoint sigue siendo síncrono para FastAPI: se ejecuta en su worker habitual,
por lo que el loop asíncrono del motor no se inserta dentro del loop del servidor.
El botón Analizar y los parámetros del endpoint no cambian. El modo demo sigue
leyendo capturas; no navega.

El adaptador transforma contadores de perfil, listas de usernames, publicaciones,
IDs, URLs, descripción, métricas y comentarios al contrato existente. Mapea
`comment_id` real a `cid`, y conserva fechas, autoría y campos opcionales de
comentarios verificables. No se confunden comentarios contados con recuperados.
Los fallos no producen perfiles de ceros ni comentarios inventados. La metadata
identifica `engine=SCRAPINGTIKTOK` y el commit de referencia.

La normalización añade únicamente soporte opcional para `created_at`, `author`
y procedencia del motor. El repositorio MongoDB, claves, relaciones, embeddings,
historial, endpoints semánticos, PCA, similitud, Big Five, SocialMind, frontend y
modelos OpenAI no se modifican. `backend/scraper.py` queda exactamente como en el
commit restaurado para compatibilidad de helpers y pruebas históricas; ni el
endpoint real ni `manage capture` lo utilizan como motor.

Archivos existentes modificados: `backend/main.py`, `backend/manage.py` y
`backend/normalizer.py`. Archivos añadidos: `reference_engine.py`,
`reference_runtime.py`, `reference_adapter.py`, el paquete vendor con fuente,
licencia, diff y manifiesto, `tests/test_reference_engine.py` y este documento.
No se añadieron dependencias.

## Verificación y resultado real

La suite completa final ejecutó 204 pruebas fuera del sandbox para permitir
Chromium y los workers del servidor. Las diez nuevas pruebas de integración
pasaron. Permanecen los cuatro fallos preexistentes de interfaz:
`test_browser` espera etiquetas Big Five antiguas y tres subcasos de
`test_socialmind_browser` esperan el texto «parcial». Una prueba de snapshot
MongoDB real se omite cuando no está disponible. Esas áreas no se modificaron.

Las nuevas pruebas cubren ejecución de los métodos originales, rehidratación,
listas mediante red, descubrimiento, video, comentarios JSON/DOM, asociación por
ID/autor, números exactos y desconocidos, persistencia en memoria e historial.
Comprueban que el endpoint no llama al motor antiguo, que las páginas lógicas
comparten estado de sesión, que CAPTCHA devuelve HTTP 502 sin guardar y que se
libera el bloqueo. Otra prueba verifica el hash de la copia original y la licencia.
Los mocks y páginas interceptadas no acreditan extracción real exitosa.

Se realizó **un intento real autorizado** del perfil `lizeth.hernadez12` usando
`reference_engine.scrape_profile()` y el Chromium persistente. Resultado:

```json
{"status":"access_restricted","reason":"TikTok solicita verificación o autenticación. Ejecuta: .venv/bin/python -m backend.manage session"}
```

El motor se detuvo ante esa pantalla. No hay cantidades nuevas comparables y no
se escribió ese intento de verificación en Atlas. No se interpreta el bloqueo
como cero publicaciones/comentarios/seguidores. La referencia aportada por el
usuario sigue siendo 10 publicaciones, 20 comentarios reportados, mejor ejecución
con 7 comentarios individuales, 10 seguidores y 0 seguidos; no es una medición de
esta integración.

## Completar acceso manualmente y repetir

1. Cerrar la consulta activa y ejecutar
   `.venv/bin/python -m backend.manage session`.
2. Completar login/verificación manualmente en Chromium, comprobar el perfil y
   un video y pulsar ENTER para guardar/cerrar. No abrir simultáneamente otra
   extracción: el bloqueo sigue siendo obligatorio.
3. Arrancar la aplicación normalmente con `./start.sh` y pulsar Analizar para
   `lizeth.hernadez12`, o ejecutar una única consulta del endpoint existente:

```bash
curl --fail-with-body 'http://127.0.0.1:8000/api/profile/lizeth.hernadez12?mode=real'
```

Esta consulta normal sí sigue el guardado habitual en Atlas. Comparar cantidad de
publicaciones, suma de contadores conocidos, cantidad de registros individuales,
publicaciones con comentarios y tamaños de las dos listas. Comparar también IDs
comunes: entre fechas distintas TikTok puede cambiar los datos y publicaciones.
Si reaparece la pantalla de acceso, detenerse; no realizar reintentos automáticos.

Limitaciones conservadas del original: orden de candidatos por ID (no prueba
cronológica global), solo enlaces `/video/` en el descubrimiento original, listas
según respuestas scene=67/21 y acceso de la sesión, límites de scroll y resultados
parciales. La privacidad, CAPTCHA, contenido no entregado y cambios del DOM no se
pueden resolver garantizando más datos. La escena de cada lista debe confirmarse
en una sesión real que permita observar las respuestas; este intento bloqueado
no la confirmó.
