# Descubrimiento automático: comparación y alcance de la corrección

## Evidencia comprobada antes de modificar código

Los últimos intentos reales del log local, a las 13:30–13:32 UTC del 2026-10-29,
recibieron HTTP principal 200. A los aproximadamente 44 segundos seguían con cero
enlaces candidatos, cero enlaces de video y sin itemList de búsqueda. El documento
estaba complete; había un script fallido, solicitudes fallidas y errores de consola.
No había marcadores reconocidos visibles de login/CAPTCHA. Esto describe un fallo
de renderizado/carga del contenido, no demuestra un cambio de selectores ni una
espera demasiado corta. No identifica todavía el recurso o condición causal exactos.

El diagnóstico visual anterior sí registró 49 candidatos y 22 enlaces de video,
incluso con un script fallido y un error JavaScript. Por tanto, un contador de errores
por sí solo no demuestra por qué el otro intento no renderiza. Tampoco estaba
registrado el tema completo, así que no se pueden equiparar retrospectivamente
ambas consultas solo porque sus URLs saneadas sean `/search`.

| Aspecto | Trabajador antes | Diagnóstico visible | Estado tras la corrección |
|---|---|---|---|
| URL/parámetros | `/search?q=` con `quote(topic, safe='')` | Igual | Un único constructor de URL; no se solicitan usernames/enlaces. |
| Sesión | Perfil persistente y lock del runtime V1 | Mismo perfil y lock | Sin copiar cookies, credenciales ni modificar el motor V1. |
| Chromium | Headless forzado | `headless=False` | El trabajador admite selección explícita del modo; registra cuál usa. No hay fallback automático ante fallos o restricciones. |
| Navegación | Esperaba commit, hasta 20 s | DOMContentLoaded, hasta 30 s | Una única función DOMContentLoaded hasta 30 s, acotada por el presupuesto restante del lote. |
| Resultados | `observe()` y SELECTORS compartidos | Los mismos | Se mantiene la espera por enlaces/JSON con elementos, vacío explícito o restricción; no se confunde DOMContentLoaded con resultados listos. |
| Guardas | Página protegida por runtime V1 | Inspección de la página real | Se conservan las guardas del trabajador; no se saltan para imitar el diagnóstico. |
| Errores | Recuentos agregados | Tipo de error y solicitud fallida saneados | El trabajador usa los mismos eventos saneados y registra cambios de estado durante la espera. |

La diferencia de modo visible/headless es comprobable en el código, pero **no está
demostrado que sea la causa de esos timeouts reales**. La comparación externa de
la misma consulta está pendiente de autorización expresa, exigida por el operador
en la tarea anterior. No se ejecutó ninguna adquisición externa en esta corrección.

## Cambios

`backend/research_tiktok_browser.py` contiene la navegación y los observadores que
antes solo estaban en el diagnóstico visual. Ambos consumidores importan ese código;
no se añadió un extractor de comentarios duplicado. Los eventos del trabajador
usan prefijo `search_*`, incluyendo estado HTTP, errores de red Chromium fijos,
tipo de recurso, familia de dominio y referencia hash sin query. No se registran
mensajes arbitrarios, cuerpos de red, cookies ni texto personal.

Se corrigió además un defecto de observabilidad reproducido con Playwright real:
el tipo de una excepción de página puede estar en `error.name`, sin aparecer en
`str(error)`. Ahora se admite exclusivamente una lista fija de nombres de errores;
el mensaje no se registra.

Si DOMContentLoaded vence pero ya hubo respuesta HTTP, el trabajador sigue esperando
resultados durante el plazo restante. El HTTP se actualiza ante cada navegación;
no se conserva por error el estado de una página anterior. Se mantienen la clasificación
de restricciones, validación de URLs, deduplicación, checkpoints y límites de scroll.

Modo normal sin ventana, compatible con el valor anterior:
`MEDIA_SCRAPER_TIKTOK_HEADLESS=1` (predeterminado). Para ejecutar la búsqueda automática
con Chromium visible como en el diagnóstico: `MEDIA_SCRAPER_TIKTOK_HEADLESS=0` al
iniciar el trabajador. Requiere una sesión gráfica disponible. No automatiza login,
CAPTCHA ni interacción con bloqueos. Esta variable solo la lee el conector temático;
el V1 por username mantiene su configuración anterior.

`tests/pilot_tiktok_mongodb.py` permite `--browser visible` o `--browser headless`,
con la misma ruta del trabajador y los límites fijos anteriores de dos publicaciones
y diez comentarios preparados. Requiere autorización externa y base aislada nueva.
No se cambió el diseño genérico de publicaciones, las rutas ni la interfaz.

## Pruebas controladas y persistencia comprobada

- 22 regresiones específicas de descubrimiento, adquisición y diagnóstico: resultados
  a los 3,2 s, timeout DOM posterior a HTTP 200 con resultados que llegan después,
  solicitud de script abortada y ReferenceError, selección explícita del modo,
  codificación del tema, restricciones, validación, privacidad y checkpoints.
  El nuevo caso de error JS detectó inicialmente el defecto de `error.name`; se
  corrigió y pasó al repetirlo junto con las tres pruebas del diagnóstico.
- Integración completa con Chromium, método V1 y MongoDB 8.2.12 reales:
  **6 pruebas satisfactorias en 21,549 s**, con páginas y comentarios interceptados.
  Una búsqueda, dos videos consecutivos y cuatro comentarios preparados confirmados.
  Se verificaron también interrupción de proceso después del commit, pausa 403,
  reintento 503, objetivo restante y límite sin declarar un objetivo incumplido.
- Base nueva `media_scraper_integration_tiktok_b28c115ec9c7`, replica set desechable
  msIntegration en `127.0.0.1:32769`, sin usar `backend/.env` ni el MongoDB existente.
  Una lectura independiente encontró seis estudios y 23 registros; todos los contadores
  prepared coincidían con sus documentos. El contenido era controlado, no de TikTok real.
- Resumen local saneado, ignorado por Git:
  `.media-scraper/diagnostics/automatic-validation-20261029-b28c115ec9c7.json`.

Tras guardar el resumen se retiró únicamente `ms-tiktok-automatic-20261029` y sus
datos tmpfs controlados. Se comprobó que el MongoDB preexistente continuaba activo
en 27017. El resumen permanece disponible; un piloto requerirá otro entorno aislado.

El recorrido de adquisición sigue siendo tema → cola de publicaciones → extractor V1
→ preparación → transacción majority de registros/contadores/checkpoint pendiente
→ confirmación → siguiente publicación. Se priorizan confirmaciones pendientes y
publicaciones ya conocidas; los errores posteriores no borran lotes guardados.

## Pendiente real

Falta comparar la misma búsqueda en ambos modos y, si es accesible, comprobar comentarios
preparados y documentos del piloto aislado con otro cliente MongoDB. No se atribuye
el fallo a headless sin esa evidencia, no se asegura que esta corrección lo resuelva
externamente y no se presentan los 23 registros controlados como comentarios reales.
No hay autorización expresa nueva para ejecutar ese piloto en esta tarea; la solicitud
de confirmación está pendiente. No se probaron ni eludieron restricciones.
