# Auditoría e integración del recorrido temático TikTok

Rama `feature/analisis-educativo`. No se modificaron el motor V1, el adaptador de
perfiles, la interfaz, embeddings, clustering, recomendaciones ni YouTube en esta
corrección. Se conservaron los cambios sin confirmar que ya tenía el repositorio.

## A. Auditoría antes de modificar código

Llamadas comprobadas leyendo la implementación, no por inferencia de los nombres:

1. `research_routes.py`: crear estudio y start/resume persisten órdenes; GET devuelve
   progreso, tareas, publicaciones y registros. Ninguna ruta ejecuta scraping.
2. `research_worker.py`: claim del estudio/tarea bajo reserva; si no hay checkpoint
   pendiente, llama a `connector_for('tiktok').read(...)` fuera de la transacción.
3. `research_tiktok.py`: búsqueda con Playwright, URLs canónicas y prefijo verificado;
   en acquire establece el autor esperado y llama a
   `TikTokScraper._extract_single_video_details(...)` del motor V1.
4. `reference_runtime.py`: perfil persistente con lock, `SharedBrowser/ContextLease`,
   guardas de acceso y comprobaciones de publicación/autoría/respuestas de comentarios.
5. `vendor/scrapingtiktok/tiktok_scraper.py`: rehidratación del video, interceptor de
   comentarios de ese video y fallback DOM; devuelve comentarios limitados y video
   verificado. No se copió ni reemplazó ese extractor.
6. V2 transforma ese resultado al contrato acotado `Page`; `validate_page()` verifica
   la correspondencia con la tarea. `research_privacy.prepare_record()` prepara los
   comentarios dentro de `research_repository.stage_page()`.
7. `stage_page()` hace commit majority de registros, contadores y checkpoint pendiente
   juntos. `confirm_page()` avanza el cursor, marca video procesado y aplica el objetivo.
   Un lote pendiente se confirma tras reinicio sin volver a invocar el conector.

V1 por username usa `reference_engine.extract_profile()` → `TikTokScraper.scrape()`
→ el mismo extractor de video → `reference_adapter.adapt_profile()`. Ese adaptador
requiere un perfil completo y produce el contrato del dashboard V1. V2 no debe
fabricar un perfil para usarlo: su contrato son comentarios preparados y metadatos
de una publicación. Las conversiones de métricas a ese contrato son necesarias;
no hay una segunda implementación de extracción de comentarios en V2.

| Área auditada | Hallazgo y decisión |
|---|---|
| Reutilización | Extractor V1, runtime, autoría, preparación, transacciones y cola ya existían. Se mantienen. |
| Duplicación | No invocar `adapt_profile()` con datos de un solo video ni copiar su extractor. No se añadió otro motor ni otra colección. |
| Navegador | Un Chromium persistente por intento, protegido por lock; cierre en finally. Reabrir por lote libera sesión durante persistencia. No se cambió V1 ni se mantuvo una sesión global nueva. |
| Carga | Se conserva la espera condicional de resultados diferidos y el timeout del lote, en lugar de inferir ausencia desde DOMContentLoaded. |
| Comentarios | Un 503 del endpoint sin comentarios podía parecer adquisición vacía exitosa. Se corrige a carga fallida reintentable; no se clasifica como restricción. |
| Datos observados | Memoria no equivale a commit. Una restricción confirmada rechaza el lote; el timeout del motor también puede impedir su devolución. Los datos previamente confirmados permanecen. |
| Checkpoints/reintentos | Se conserva el prefijo validado. La planificación agotaba descubrimiento antes de procesar videos disponibles; ahora prioriza confirmación pendiente y después adquisición, incluyendo su espera de reintento. |
| Persistencia/progreso | La transacción de stage ya era correcta. Faltaban eventos que distinguieran commit de memoria, acotar la petición al objetivo restante y limpiar el error previo tras confirmar una reanudación exitosa. |

## B. Correcciones integradas

- `ResearchRepository.next_task()` selecciona, solo para TikTok: confirmación
  pendiente → video ya encolado → siguiente página de descubrimiento. Claim y release
  utilizan la misma selección. Si ese video espera un reintento, el estudio se agenda
  para su plazo; no vuelve a buscar ni gira en vacío por una tarea de descubrimiento
  que sigue disponible. La planificación de otras fuentes conserva su comportamiento.
- El trabajador limita la petición de comentarios al menor entre tamaño de lote y
  objetivo restante. Se conserva el lookahead de un comentario del conector y el
  máximo por publicación. Privacidad/exclusiones pueden exigir continuar con otro lote.
- `stage_page()` devuelve los contadores del commit. `worker_batch_staged` los registra
  solo después de que la transacción retorna; `worker_batch_confirmed` indica el avance
  del checkpoint y si se recuperó un pendiente. Ninguno registra texto ni identidades.
- Una confirmación TikTok exitosa limpia `last_error`/`stop_reason` anteriores. El
  objetivo y los límites siguen determinándose por datos persistidos, no observados.
- `AcquisitionAccessEvidence` distingue errores HTTP del documento/endpoint objetivo
  de errores secundarios. Si el endpoint falla con HTTP no restrictivo y el motor
  devuelve cero comentarios, se reintenta como `source_load_timeout` sin marcar el
  video procesado. Si ya hay comentarios válidos, un fallo no restrictivo no borra ese
  lote. Un 401/403/429 confirmado, login/CAPTCHA o guarda original mantiene la pausa.

## C. Validación integral local con MongoDB real

Ejecutada el 2026-10-29: **6 pruebas, 22,357 s, cero errores/fallos**. Chromium y el
método V1 realmente se ejecutaron. Todas las solicitudes de páginas/comentarios se
interceptaron y sus contenidos eran controlados. Los sleeps internos se redujeron
solo en el fixture; el código V1 no cambió. No hubo adquisición externa.

Servidor MongoDB **8.2.12**, replica set de un nodo `msIntegration`, contenedor nuevo
`ms-tiktok-flow-20261029`, imagen local `mongo:8` sin descarga; puerto
`127.0.0.1:32768`. Datos en tmpfs, sin volúmenes del host. La base nueva fue
`media_scraper_integration_tiktok_246d30a14770`; el guard existente rechazaba bases
preexistentes, puertos de producción, credenciales y servidores remotos. No se leyó
`backend/.env` ni se usó el perfil real del navegador. El MongoDB preexistente del
equipo no participó en las pruebas.

Se probaron rutas FastAPI de crear/start/progreso/resume/registros con dependencia
del repositorio apuntando exclusivamente a esa base. Tras cada tick se consultaron
registros con **otro MongoClient**. Se comprobaron igualdad `prepared = documentos`,
`received = prepared + duplicates + excluded`, unicidad, privacidad, máximo del objetivo,
publicaciones procesadas y tareas/cursors. El manifest marca contenido controlado.

| Caso | Evidencia comprobada |
|---|---|
| Tema → búsqueda → dos videos V1 → MongoDB | Una búsqueda, dos llamadas V1 en orden, cuatro registros preparados confirmados, objetivo cuatro alcanzado; la búsqueda pendiente no se repitió. |
| Muerte después de stage y antes de confirm | Un subproceso terminó realmente con `os._exit(71)`; otro cliente encontró dos registros y un checkpoint pendiente. Nuevo trabajador confirmó sin invocar el conector, procesó el siguiente video y terminó con cuatro registros sin duplicación. Se adelantó el reloj de aplicación 61 s para vencer la reserva; no se esperó su vencimiento real. |
| HTTP 403 confirmado en segundo video | Pausa con dos registros previos conservados, sin checkpoint del video bloqueado; GET no ejecutó adquisición. Reanudación explícita con fixture ya accesible terminó en cuatro y limpió el error anterior. |
| HTTP 503 transitorio de comentarios | Se conservaron dos registros y solo un video procesado; se esperó el reintento sin redescubrir; recuperación del mismo video terminó en cuatro. |
| Límite de publicaciones/comentarios | Con objetivo cinco y máximo de dos videos × dos comentarios, terminó `exhausted`, cuatro confirmados, 80%; no afirmó objetivo cumplido. |
| Objetivo restante | Con objetivo tres, segundo video pidió como máximo dos comentarios por el lookahead, no cincuenta; solo tres quedaron preparados. |

Auditoría independiente final de la base: **6 estudios, 23 registros, 12 publicaciones,
18 tareas**. Todos los contadores prepared coincidían con los documentos de su estudio.
Solo existían las cuatro colecciones research_* y `_integration_manifest`.
Después se detuvo únicamente el contenedor nuevo; `--rm` retiró sus tmpfs y datos
controlados. Se comprobó que `aseguramiento-calidad-mongodb` seguía activo en su
puerto original 27017. Un piloto posterior requiere otro servidor/base aislados nuevos.

Regresión específica adicional: **18 pruebas satisfactorias** de API, adquisición,
descubrimiento, checkpoint y extractor V1 existente. Incluye resultados diferidos
3,2 s, diez comentarios seguidos de errores secundarios, restricciones auténticas,
autoría incorrecta y ausencia de falsa preparación con HTTP 503. La prueba ASGI del
contrato tuvo inicialmente un timeout dentro del sandbox y pasó al repetirla fuera
de él. No se ejecutaron benchmarks de 400/600/1.000 registros ni adquisición masiva.

Reproducción del recorrido local, con un servidor desechable creado como se describe
en `mongodb-integration.md` y sustituyendo PUERTO por su puerto aleatorio:

```bash
.venv/bin/python -B tests/integration_tiktok_mongodb.py \
  --uri 'mongodb://127.0.0.1:PUERTO/?replicaSet=msIntegration&directConnection=true' \
  --confirm-isolated
```

## Evidencia real y pendientes

La evidencia real anterior acredita resultados visibles de bitcoin y diez comentarios
en memoria en otra ejecución, seguida de una pausa antes de persistir. No acredita
el recorrido real completo de búsqueda → comentarios preparados → commit → siguiente
video tras esta corrección. La integración está **probada localmente con MongoDB real
y contenido controlado**, no validada integralmente con datos externos reales.

Se preparó `tests/pilot_tiktok_mongodb.py`, que exige `--authorized-external` y
`--confirm-isolated`, URI local aislado y base nueva. Sus límites fijos son dos
publicaciones, cinco comentarios por publicación, objetivo diez, presupuesto 120 s
y ocho ticks como máximo. Un lote iniciado antes de vencer el plazo puede tardar
hasta su timeout configurado antes del cierre. No usa fixtures ni altera V1; utiliza
el perfil local con su lock y se detiene ante una restricción confirmada. Imprime
por separado progreso y recuento final leído con otro cliente. Se requiere la
confirmación expresa del operador antes de ejecutarlo desde esta tarea.

Persisten límites deliberados: los checkpoints de UI son prefijos locales, no cursores
oficiales; reordenamientos durante una paginación provocan pausa `checkpoint_changed`
y preservan lo ya guardado. Una página adicional puede requerir volver a observar ese
prefijo, pero no se redescubre mientras haya videos conocidos pendientes. No se afirma
cobertura completa de TikTok (`source_complete=false`). Un timeout antes de devolver
el motor no autoriza persistir comentarios aún no validados ni ignorar un acceso negado.
No se probaron caídas del servidor, elecciones entre nodos ni durabilidad física del tmpfs.

Archivos de esta corrección: `backend/research_tiktok.py`,
`backend/research_worker.py`, `backend/research_repository.py`,
`tests/test_research_tiktok_acquisition.py`, `tests/integration_tiktok_mongodb.py`,
`tests/pilot_tiktok_mongodb.py` y este documento. Sin commits ni push.
