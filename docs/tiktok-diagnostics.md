# Diagnóstico local del trabajador TikTok temático

## Adquisición: diez comentarios en memoria y pausa posterior

Se revisó el log local de la ejecución real de 2026-10-29, sin acceder a TikTok
ni escribir en MongoDB. En la adquisición que falló:

- 12:34:35 UTC: documento principal 200, `video_document`, JSON de video presente,
  documento interactive; sin marcadores visibles de login/CAPTCHA.
- 12:34:39 UTC: antes de cerrar, principal 200, mismo JSON, documento complete;
  sin login/CAPTCHA visibles. Nueve solicitudes fallidas, un script fallido,
  un error JavaScript y once errores de consola.
- Luego `comments_observed` indicó diez comentarios y publicación verificada;
  el traceback señala el antiguo `if restricted: raise AccessRestricted` en la
  línea 159 de research_tiktok.py. No se emitió `comments_processed` para ese lote.

La condición antigua retenía un booleano por cualquier respuesta 401/403/429 del
contexto compartido cuyo host fuera tiktok.com o www.tiktok.com. No verificaba
recurso, frame, endpoint ni video. Por tanto, sabemos que hubo al menos una de esas
respuestas HTTP: los errores JavaScript y requestfailed no activaban directamente
esa lista. No sabemos cuál respuesta fue: el registro anterior no guardaba su
alcance ni estado exacto. No es posible afirmar retrospectivamente si la pausa
real fue un falso positivo o una denegación auténtica del endpoint de comentarios.
HTTP principal 200 y ausencia de un CAPTCHA visible no descartan una denegación API.

La corrección mantiene el control HTTP, limitado a las páginas que abre este
extractor y a:

- Documento del frame principal: 401/403/429.
- Fetch/XHR del frame principal al endpoint `/api/comment/list/` de TikTok,
  con `aweme_id` igual al video solicitado: 401/403/429.
- Login o CAPTCHA/verificación reconocidos por el diagnóstico antes de cerrar,
  y cualquier `AccessRestricted` lanzado por las guardas originales del motor.

Los demás errores HTTP se registran como `acquisition_http_error`, sin URL ni
query, con `establishes_access_restriction=false`. Abortos, errores JavaScript,
estructuras incompletas y fallos HTTP distintos no se reclasifican como acceso
restringido por este control. Una estructura no verificada conserva su error de
procedencia/estructura; no se acepta por haber comentarios.

`acquisition_access_evidence` identifica causa, HTTP y fase cuando están disponibles.
`acquisition_access_decision` registra decisión, evidencia confirmada limitada a
diez entradas (con contador total), cantidad de HTTP secundarios y snapshots
saneados antes/después. `engine_access_guard=true` preserva una restricción emitida
por el motor aunque la inspección posterior ya no pueda ver el mismo marcador.
`acquisition_batch_rejected` aclara cuántos comentarios observados no se devolvieron
por una restricción confirmada. No se guardan cuerpos HTTP, credenciales, mensajes
arbitrarios de errores ni texto/identidad de comentaristas en estos eventos.

El motor existente usa rehidratación JSON para verificar ID/autoría y extraer
métricas del video. No extrae directamente comentarios embebidos en ese JSON:
su lista de comentarios viene del interceptor de respuestas de comentarios
validadas para el video, o del fallback DOM. La marca `_verified` corresponde al
video, no demuestra persistencia ni identifica por sí sola cuál fuente proporcionó
los comentarios. El adaptador conserva validaciones y deduplicación por ID o huella.

La excepción ocurre antes de convertir y devolver las filas: `read()` la traduce
a `SourceFailure('access_restricted', False)`, de modo que el trabajador no llega a
`validate_page()`, `stage_page()` ni `confirm_page()` para ese lote. Los diez quedan
solo en memoria. No se introduce persistencia parcial ante una restricción real.
El log inmediatamente anterior mostraba otra publicación con cero comentarios
observados/procesados; una publicación procesada no implica comentarios preparados.

La persistencia la realiza `stage_page()` transaccionalmente (registros preparados,
contadores y checkpoint pendiente) y `confirm_page()` confirma el avance del cursor.
Para acreditar persistencia REAL falta consultar los registros preparados del mismo
study_id/publication_id, sus contadores y el estado/checkpoint de la tarea en MongoDB
después del commit. Diez observados o diez procesados en logs no son esa prueba.
No se consultó ni modificó la base real en esta corrección.

Pruebas específicas: `tests/test_research_tiktok_acquisition.py`, con Chromium y
respuestas locales interceptadas, además de una base de prueba en memoria. Cubren
diez comentarios seguidos de HTTP secundario 403/429, abortos/JS, denegación del
endpoint del video, denegación principal, login/CAPTCHA, autoría ajena, deduplicación,
privacidad y no avance del checkpoint/no preparación ante restricción confirmada.
Son pruebas locales, no evidencia de adquisición o persistencia reales nuevas.

## Espera del descubrimiento temático

El trabajador comparte con el diagnóstico visual `observe()` y los selectores de
enlaces candidatos. Tras confirmar la navegación espera asíncronamente enlaces de
video, elementos de itemList o un marcador vacío visible, comprobando acceso durante
la espera. DOMContentLoaded, un itemList vacío y una pausa transcurrida no acreditan
resultados disponibles. Las restricciones se detectan sin esperar al plazo final.

La espera inicial consume el presupuesto restante de `batch_timeout_seconds`,
descontando la apertura de Chromium y reservando un segundo para cierre/diagnóstico.
El timeout externo del lote sigue activo. Tras cada desplazamiento se espera un
cambio en los recuentos hasta dos segundos, siempre dentro del presupuesto restante;
se conservan max_scrolls y el límite de dos desplazamientos sin nuevas publicaciones.

- `source_load_timeout` (reintentable): navegación agotada, documento pendiente,
  indicador de carga, errores de navegador o HTTP de carga sin resultados al vencer
  el plazo. Los errores secundarios son pistas, no una prueba causal concluyente.
- `source_structure_changed`: sin resultados reconocidos tras agotar la espera,
  con documento completo y sin señales de carga fallida. Sigue significando estructura
  no reconocida; no demuestra por sí solo un cambio del sitio.
- `access_restricted`: login, CAPTCHA/verificación, redirección no admitida o HTTP
  principal 401/403/429. No se elude.

`search_results_wait` registra la duración de espera; `first_search_result` mide
segundos desde el inicio del descubrimiento hasta la primera publicación validada.
`valid_videos_detected` y el cierre de `results_detection` incluyen publicaciones
válidas deduplicadas. URLs, checkpoints y extracción de comentarios mantienen sus
validaciones anteriores.

La regresión local `tests/test_research_tiktok_discovery.py` incluye una página con
itemList inicialmente vacío que añade enlaces a los 3,2 segundos; todas las respuestas
se interceptan localmente. La evidencia real de `bitcoin` (49 candidatos y 22 enlaces
de video) la aportó el operador antes de esta corrección. Esta corrección no ejecutó
otra adquisición real ni acredita extracción real de comentarios.

## Inspección visual real, sin trabajador ni MongoDB

Desde la raíz del repositorio, en una terminal dentro de una sesión gráfica local:

```bash
MEDIA_SCRAPER_RESEARCH_LOG_LEVEL=INFO .venv/bin/python -m backend.manage tiktok-visual-diagnostic
```

El comando pide el tema por terminal (puede pasarse también con `--topic`). Usa el
mismo perfil persistente y bloqueo de sesión del conector, con `headless=False`.
No ejecutar simultáneamente con un trabajador que esté usando ese perfil: el
bloqueo existente impide el acceso concurrente. El subcomando es la activación
expresa; no requiere habilitar adquisición masiva ni iniciar una investigación.

Abre una página real de búsqueda y la mantiene abierta hasta cerrar la pestaña o
pulsar Ctrl+C. No llama al descubrimiento, extractores de publicaciones/comentarios,
repositorios ni MongoDB. No hace scroll, reintentos automáticos ni acciones sobre
login/CAPTCHA. TikTok puede efectuar sus propias solicitudes para renderizar la
página, pero el comando no lee ni guarda sus cuerpos. La sesión persistente puede
actualizar su estado local normal; sus cookies nunca se copian al diagnóstico.

Observar la URL completa en la barra de Chromium y el contenido real: pantalla en
blanco, indicador de carga, mensaje de error, consentimiento, login, verificación
o tarjetas de resultados. Para inspeccionar el error exacto o el recurso fallido,
abrir manualmente F12 → Console y Network dentro de esa ventana. No exportar HAR
ni copiar mensajes privados al log. Los mensajes arbitrarios y las URLs de recursos
se omiten deliberadamente de los registros del programa.

La terminal y `worker.jsonl` muestran eventos `visual_*` en tiempo real:

- Navegación solicitada/confirmada, URL sin query, HTTP principal, DOMContentLoaded
  y evento load; un timeout no cierra la ventana.
- Solicitudes fallidas con tipo, familia de host permitida, referencia hash sin query
  y código Chromium fijo (por ejemplo `net::ERR_CONNECTION_RESET`). Errores HTTP
  secundarios también se registran, pues HTTP 4xx/5xx no emite requestfailed.
- Tipo de excepción JavaScript y ocurrencias de errores de consola, sin sus mensajes,
  stacks de navegador, tokens, cookies, nombres de recursos ni datos de personas.
- Estado observado cada dos segundos, registrado al cambiar o cada diez segundos.

`visual_state` distingue:

| Estado | Evidencia |
|---|---|
| `content_pending` | Documento no completo, indicador de carga visible o primeros 30 segundos sin resultados. Es una ventana de observación, no una promesa de carga. |
| `blank_page` | Tras esa ventana, documento completo sin texto ni elementos visuales reconocidos. No demuestra por sí solo la causa. |
| `recognized_results` | Enlaces de video o itemList con elementos; un array vacío no basta. |
| `recognized_empty_results` | Marcador explícito de resultados vacíos. |
| `access_restricted` | Login, CAPTCHA/verificación o HTTP 401/403/429. Solo observar y detener; no se elude. |
| `load_error` | HTTP de error principal distinto de las restricciones anteriores. |
| `unrecognized_content` | Documento con contenido pero sin resultados ni patrón de acceso reconocido. Comparar visualmente y revisar Console/Network. |

HTTP 200 y evento load no garantizan que la aplicación haya renderizado resultados.
Si aparecen errores de scripts/JavaScript, investigar carga antes de atribuir el
fallo a selectores. Si se ven tarjetas reales pero los contadores siguen a cero,
eso aporta evidencia concreta de incompatibilidad de selectores/JSON. Este modo
no emite `source_structure_changed` ni pausa una investigación.

No genera PNG ni vuelca DOM: la inspección visual ocurre en la ventana original,
sin sustituirla por la representación JSON saneada del modo de captura anterior.
Los únicos artefactos de este comando son los logs saneados ya descritos abajo.

Pruebas del comando: `tests/test_research_visual_diagnostic.py` usa exclusivamente
dobles de navegador, sin abrir Chromium ni acceder a TikTok/MongoDB.

Esta instrumentación no modifica el scraper por username ni demuestra adquisición
real. Las verificaciones de esta entrega usan Chromium y respuestas interceptadas;
no se ejecutaron solicitudes externas ni escrituras en MongoDB real.

## Activación y ubicación

El comando existente configura logs JSON estándar `logging` por defecto en INFO:

```bash
.venv/bin/python -m backend.manage research-worker
```

Cada línea se muestra en **stderr de la terminal** y se guarda en
`.media-scraper/diagnostics/worker.jsonl`, relativa al repositorio. La carpeta está
cubierta por la regla Git existente `.media-scraper/`; no agregar sus archivos a Git.
Directorio 0700, archivos 0600. Rotación a 1 MB con tres copias anteriores.
No hace falta `logging.basicConfig` ni una dependencia adicional.

Nivel explícito (se aplica al iniciar el proceso):

```bash
MEDIA_SCRAPER_RESEARCH_LOG_LEVEL=INFO .venv/bin/python -m backend.manage research-worker
```

Niveles admitidos: DEBUG, INFO, WARNING, ERROR y OFF. Los eventos operativos son
INFO, las excepciones ERROR y los fallos al producir diagnóstico WARNING. DEBUG
no registra cuerpos adicionales. Para desactivar ambos tipos de diagnóstico:

```bash
MEDIA_SCRAPER_RESEARCH_LOG_LEVEL=OFF MEDIA_SCRAPER_TIKTOK_DEBUG=0 .venv/bin/python -m backend.manage research-worker
```

OFF desactiva este logger; no modifica posibles logs de otras bibliotecas. No es
necesario ejecutar otro trabajador para observar el que ya está activo:

```bash
tail -F .media-scraper/diagnostics/worker.jsonl
```

Los cambios de nivel/debug requieren reiniciar el trabajador con el entorno deseado.
Estos comandos no conceden ni cambian el permiso de adquisición externa, que
conserva sus controles anteriores. No se modificaron variables locales al probar.

## Capturas optativas

Solo con activación expresa:

```bash
MEDIA_SCRAPER_TIKTOK_DEBUG=1 MEDIA_SCRAPER_RESEARCH_LOG_LEVEL=INFO .venv/bin/python -m backend.manage research-worker
```

Se guardan pares `<diagnostic_id>.json` y `<diagnostic_id>.png` en la misma carpeta.
`diagnostic_saved` identifica el par en el log. Se generan al inspeccionar documentos,
al cerrar páginas de publicación y al fallar la búsqueda; puede haber varios por lote.
Desactivar capturas: omitir la variable o usar `MEDIA_SCRAPER_TIKTOK_DEBUG=0`.

El PNG es una screenshot de una **vista separada y saneada del diagnóstico**, no
una fotografía de la página original. Contiene clasificación, URL saneada, estado,
recuentos de selectores y presencia de JSON. Así se evita capturar sesión, avatares,
autores, comentarios, formularios o desafíos. No permite inspeccionar el diseño
visual original. El resumen no contiene HTML, texto del DOM, valores de atributos,
cookies, almacenamiento local ni cuerpos de red. La vista usa CSP sin recursos de
red. Los artefactos no se rotan automáticamente: revisar y retirar los propios
archivos locales cuando ya no sean necesarios.

## Eventos y correlación

`worker_batch_started` y `worker_batch_finished` incluyen estudio, tarea y fuente.
El contexto se propaga a los eventos del navegador; no se registra el tema ni el
cursor. Las etapas emiten `stage_started`, `stage_finished` o `stage_failed`:

- `chromium_open`: apertura del contexto persistente por el motor activo.
- `search_navigation`: navegación hasta DOMContentLoaded.
- `document_inspection`: inspección inicial del documento.
- `results_detection`: recorrido de detección y extracción de publicaciones.
- `publication_navigation`: navegación realizada por el extractor existente.
- `publication_and_comments_extraction`: extracción original de métricas/comentarios.
- `tiktok_batch`: duración completa del intento del adaptador.

Los eventos terminados/fallidos incluyen duración en segundos. `results_detected`
registra paso de desplazamiento, enlaces candidatos y publicaciones con metadatos;
el final registra publicaciones válidas. `comments_observed` y `comments_processed`
registran cantidades, sin conservar texto o identidad de comentaristas en logs.

`browser_diagnostic` incluye:

- URL final sin query, fragmento ni credenciales; rutas de autores e identificadores
  se sustituyen por marcadores. Orígenes ajenos y rutas desconocidas se omiten.
- Título solo si corresponde a una etiqueta estática conocida de TikTok; otros
  títulos se omiten, conservando su longitud. Un título puede contener datos personales.
- Estado HTTP principal cuando se observó, estado de carga del documento, recuentos
  y visibilidad de selectores reconocidos, presencia/validez del script JSON, scope,
  bloque de búsqueda, itemList y detalle de video. No se registran valores del JSON.
- Contadores de solicitudes fallidas, scripts fallidos, errores JavaScript y errores
  de consola; nunca se registran sus mensajes, URLs ni contenido.
- `candidate_video_links` distingue enlaces de video de otros enlaces candidatos;
  `search_json_items` indica cuántos elementos contiene itemList (null si falta).
  Un array vacío por sí solo no demuestra que TikTok mostró una página sin resultados.
- `load_problem_suspected` señala documento no completo, errores de navegador o
  HTTP de error. Es una pista, pues también puede fallar un recurso secundario.
  Si no se puede inspeccionar el DOM, `diagnostic_failed` conserva URL saneada,
  HTTP disponible y `inspection_unavailable`, además del traceback saneado.

Las excepciones incluyen tipo y traceback local estructurado (archivo, función,
línea, máximo 20 marcos), sin mensaje de excepción, variables locales ni líneas de
código. Esto preserva el punto de fallo sin filtrar una URL privada o un payload.
La respuesta pública conserva códigos seguros y la interfaz los traduce a mensajes
comprensibles. `source_structure_changed`, por ejemplo, muestra: «No se reconocieron
los resultados de TikTok. Revisa el diagnóstico del trabajador».

## Cómo interpretar un fallo

| Evidencia | Interpretación |
|---|---|
| `stage_failed` en `chromium_open` | Fallo al abrir Chromium/contexto. Revisar tipo y marcos; no confundir con selectores. |
| Navegación fallida, timeout o `document_loading` | Carga no completada; no acredita cambio de estructura. |
| `http_load_error`, HTTP 4xx/5xx | Respuesta de error de carga. |
| `http_access_restricted`, HTTP 401/403/429 | Restricción de acceso observada. |
| `authentication` | Ruta de login/signup o diálogo de autenticación visible. |
| `captcha_or_verification` | Ruta o marcador visible de verificación. No se elude. |
| `recognized_empty_results` | Marcador vacío reconocido; no inferirlo por ausencia de enlaces. |
| `search_results_markers` | Documento de búsqueda con enlaces de video o itemList reconocidos; revisar cantidad válida y procedencia. |
| `search_structure_unknown` | Ruta de búsqueda sin marcadores reconocidos. Puede ser estructura cambiada, renderizado incompleto o fallo JS; todavía no prueba un cambio de TikTok. |
| `unknown_document` | Documento distinto al esperado sin patrón conocido. |

Comparar diagnóstico inicial y final de la misma tarea. Si el documento está
completo pero hay scripts/red fallidos o errores JS, investigar carga antes de
atribuirlo a selectores. Si la carga fue correcta, no hay restricciones visibles y
siguen ausentes los selectores y JSON soportados, queda evidencia de estructura
**no reconocida por este adaptador**, no una prueba concluyente de que TikTok cambió.
La clasificación depende de los marcadores conocidos; un bloqueo con estructura
nueva también puede terminar como desconocido. No se añaden intentos de evasión.

Los checkpoints y contadores de MongoDB, los permisos y el modo de recuperación
permanecen iguales. Una pausa previa requiere reanudación explícita; activar logs
no reanuda ni inicia adquisición.

## Pruebas específicas

```bash
PYTHONPATH=tests .venv/bin/python -B -m unittest test_research_diagnostics
node --test tests/test_research_diagnostics.cjs
```

Cubren JSON, archivo/terminal, OFF, permisos locales, traceback saneado, errores
públicos, clasificación de página, captura optativa, ausencia de secretos/textos,
inspección tras guardas de acceso y eventos del extractor original con fixtures.
No ejecutar la suite completa para esta corrección de observabilidad.

Las pruebas específicas incluyen siete pruebas Python y una JavaScript. No se ha diagnosticado
retroactivamente la causa de la investigación real: no había evidencia suficiente
y esta tarea no ejecutó adquisición externa.
