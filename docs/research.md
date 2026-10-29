# Investigación Temática — núcleo de adquisición, fase 1

Este módulo procesa exclusivamente **Datos de prueba — No reales**. Admite temas
libres y objetivos personalizados; no contiene catálogos disciplinares. No busca
TikTok, no ejecuta Playwright, no llama OpenAI ni construye clasificación/clustering.
Los datos sintéticos prueban el circuito de adquisición, no la pertinencia temática
ni el acceso a una plataforma real.

## Arquitectura y ejecución

FastAPI registra `research_routes`. Crear una investigación guarda configuración y
una tarea de descubrimiento, inicialmente sin ejecutar. Un comando explícito la
pone en cola. Un proceso local separado (`research_worker`) reclama investigaciones,
lee una sola página del conector, prepara datos, guarda un lote y confirma el cursor.
La interfaz consulta el progreso mediante GET; abrir la pestaña no inicia trabajo.

Se reutiliza `database.get_database()` y su configuración existente, sin tocar las
colecciones previas. Como el repositorio original, el módulo requiere MongoDB con
transacciones (Atlas o replica set). No hay fallback silencioso a escrituras parciales
en una instancia standalone. Esta entrega no se ejecutó contra la base real.
Las transacciones solicitan confirmación `majority` y limitan cada commit a diez
segundos, siguiendo el patrón de persistencia del proyecto.

```bash
# Terminal 1: aplicación
bash start.sh

# Terminal 2: trabajador continuo; usa únicamente las cuatro colecciones research_*
.venv/bin/python -B -m backend.manage research-worker

# Procesar como máximo un lote disponible y cerrar
.venv/bin/python -B -m backend.manage research-worker --once

# Ajustar el intervalo cuando no hay trabajo disponible
.venv/bin/python -B -m backend.manage research-worker --poll-seconds 2
```

El trabajador se cierra con Ctrl+C y libera el cliente. Una muerte abrupta conserva
lo confirmado; la reserva se puede reclamar tras vencer. Los errores de base se
presentan con mensajes seguros; reparar la conexión y reiniciar el trabajador es
manual. No se modificaron archivos `.env` ni dependencias.

## Modelo de datos e índices

| Colección | Datos | Índices adicionales al `_id` |
|---|---|---|
| `research_studies` | Tema, descripción, fuente, objetivo, límites, contadores, estado, reserva y secreto de deduplicación interno | `(status,next_run_at,lease_until)`, `(created_at,_id)` |
| `research_tasks` | Tipo, publicación, cursor, offset, confirmación pendiente, intentos, fallos, fechas y reserva | Único `(study_id,kind,publication_id)`; `(study_id,status,next_attempt_at)` |
| `research_publications` | Procedencia, descripción preparada, métricas permitidas, fecha de descubrimiento y cobertura | Único `(study_id,source,publication_id)` |
| `research_records` | Texto preparado, publicación, clave interna, marcador sintético y versión de privacidad | Único `(study_id,record_key)`; `(study_id,_id)` |

Solo crear o iniciar el trabajador asegura índices. Las consultas GET no crean
índices ni procesan fuentes. Listas, tareas, publicaciones y registros se paginan
(máximo 100 por respuesta). No se guardan cuerpos originales ni snapshots del corpus.

## API

| Método y ruta | Operación |
|---|---|
| `GET /api/research/sources` | Fuente sintética y límites del servidor |
| `POST /api/research/studies` | Crear, 201 |
| `GET /api/research/studies` | Listado paginado |
| `GET /api/research/studies/{id}` | Detalle |
| `GET /api/research/studies/{id}/progress` | Estado y contadores |
| `POST /api/research/studies/{id}/start` | Encolar, 202 |
| `POST /api/research/studies/{id}/pause` | Revocar trabajo y pausar |
| `POST /api/research/studies/{id}/resume` | Encolar una pausa, 202 |
| `POST /api/research/studies/{id}/cancel` | Revocar trabajo y cancelar |
| `GET /api/research/studies/{id}/records` | Registros preparados paginados |
| `GET /api/research/studies/{id}/tasks` | Tareas, errores y checkpoints paginados |
| `GET /api/research/studies/{id}/publications` | Publicaciones y cobertura paginadas |

Todas las respuestas de investigación tienen contratos Pydantic en `/docs`.
Listados aceptan `offset` (0–1.000.000) y `limit` (1–100).
IDs no válidos/parámetros: 422; investigación ausente: 404; transición inválida:
409; almacenamiento inaccesible: 503. Abrir la pestaña no genera adquisiciones.

Ejemplo de solicitud, con configuración sintética explícita:

```json
{
  "topic": "Tema libre introducido por el usuario",
  "description": "Validación del procesamiento con datos de prueba",
  "source": "synthetic",
  "target_records": 1000,
  "limits": {
    "batch_size": 50,
    "lease_seconds": 60,
    "max_attempts": 3,
    "time_budget_seconds": 300
  },
  "source_config": {
    "publications": 20,
    "comments_per_publication": 80,
    "failure_mode": "none",
    "failure_stage": "acquire"
  }
}
```

Objetivo mínimo 1, máximo predeterminado 10.000. El operador puede definir
`MEDIA_SCRAPER_RESEARCH_MAX_RECORDS` en el entorno del proceso (y del servidor),
sin cambiar código. Lote 1–100, reserva 10–300 s, intentos consecutivos por página
1–5 y presupuesto activo 1–3600 s. No se cambia el objetivo de una investigación
ya creada. Las cantidades disponibles no están garantizadas.

## Estados y transiciones

Investigación:

```text
draft --start--> queued --> discovering --> acquiring
                              |                |
                              +---pause--------+--> paused --resume--> queued

draft / queued / discovering / acquiring / paused --cancel--> cancelled

Trabajo activo --> target_reached | exhausted | partial | failed
Presupuesto activo agotado --> paused (time_budget_reached)
```

`target_reached`: preparados únicos alcanzan el objetivo; quedan tareas canceladas
por el límite. `exhausted`: se agotó la fuente sin alcanzar el objetivo y sin tareas
fallidas. `partial`: se agotaron las tareas, hay fallos y existen registros preparados.
`failed`: hay tareas fallidas y no hay registros preparados. Una investigación puede
alcanzar el objetivo pese a algún fallo; `failed_tasks` y `last_error` lo mantienen
visible. Ningún estado terminal admite start/resume/pause; crear otro estudio es
una acción nueva. Reanudar una pausa renueva su presupuesto activo, conserva datos,
errores históricos y duración acumulada.

Tareas: `queued -> processing -> queued` (página adicional) o `completed`;
`processing -> retry_wait -> processing`, o `failed`. Cancelar el estudio o alcanzar
el objetivo marca las tareas restantes `cancelled`. Pausar revoca la reserva del
estudio; una tarea puede permanecer `processing` sin ejecutor válido hasta su siguiente
reclamación. Por eso el estado de investigación no se deduce de una tarea aislada.

## Reservas, lotes e interrupciones

Se serializa la adquisición por estudio mediante una reserva atómica con token
aleatorio y vencimiento. Cada tarea refleja su propietario y plazo. Toda transacción
de escritura valida y renueva la reserva del estudio; un trabajador anterior pierde
el derecho de confirmar tras vencimiento/reclamación, pausa o cancelación. El token
se comprueba en la tarea. Dos trabajadores no pueden mantener dos reservas vigentes
del mismo estudio. Solicitudes externas podrían repetirse tras un fallo: no existe
garantía de procesamiento exactamente una vez a nivel de red.

1. Leer una página acotada y validar fuente, tipo, cursor y publicación.
2. Preparar campos y textos; descartar registros inutilizables.
3. Una transacción guarda publicaciones/registros, incrementos de contadores y
   `pending` (cursor/offset siguiente y condiciones de fin).
4. Otra transacción confirma `pending` en el checkpoint y libera la tarea.

Si el proceso cae tras 3 y antes de 4, el siguiente trabajador **confirma el lote
ya guardado**, sin repetir la lectura ni sus contadores. Si una transacción aborta,
el lote se revierte. Los índices únicos protegen publicaciones/registros repetidos.
Si el objetivo corta una página, se conserva su cursor y offset consumido. Los
contadores satisfacen `received = prepared + excluded + duplicates` para comentarios
consumidos; las publicaciones no contribuyen al objetivo.
Una observación repetida conserva el primer registro preparado guardado mediante
`$setOnInsert`; no sobrescribe su texto ni incrementa la cantidad preparada.

Los fallos transitorios tienen espera exponencial acotada y máximo de intentos por
página. `next_run_at` impide que una investigación esperando su reintento monopolice
el sondeo. No se conserva contenido de excepciones del conector en errores públicos.
La duración activa mide ciclos de procesamiento, excluyendo espera entre sondeos;
una caída abrupta puede perder la medición del ciclo, pero no sus datos guardados.

## Conector sintético y extensibilidad

`Connector.read(...) -> Page` recibe tema, configuración, tipo de operación,
publicación, cursor, límite e intento. Produce solo una página, con procedencia
explícita. Se valida antes de guardar. La fuente de prueba genera el texto a partir
del tema sin interpretarlo y repite IDs deliberadamente; también introduce entradas
vacías e identificadores directos de prueba. `failure_mode=transient` falla una vez
en la primera publicación; `permanent` falla esa publicación; `failure_stage=discover`
permite comprobar fallos del descubrimiento. No hay datos reales ni filtros temáticos.

Para una fuente real: acreditar autorización, añadir su conector y contratos de
configuración/capacidades al registro, adaptar sus IDs y cursores al contrato,
probar procedencia y paginación, imponer timeouts menores que la reserva y validar
cuotas/retención. Los contratos públicos de esta fase solo admiten `synthetic` y
marcadores `true`: habrá que extenderlos explícitamente para otra fuente. La lógica
de checkpoints/reservas no necesita reescribirse. No se implementa evasión de acceso.

## Privacidad y límites

`research_privacy.prepare_record` produce una lista permitida de campos. Elimina
autores, fotografías y enlaces de perfil; transforma correos, menciones, URLs,
teléfonos y secuencias numéricas largas. Rechaza vacíos, textos enormes, controles
binarios y textos sin contenido aprovechable tras la transformación. Las descripciones
de publicaciones también pasan por preparación. El tema/descripción del estudio
son metadatos introducidos por el usuario: la interfaz pide no incluir datos personales.

La clave de deduplicación es HMAC del ID de registro y publicación, con un secreto
aleatorio por estudio. No depende del username. Se conserva internamente para poder
reanudar; la API no devuelve secreto, clave ni ID de comentario original. Es
seudonimización, no anonimización irreversible. La detección no reconoce todos los
nombres, direcciones o datos contextuales y puede transformar números legítimos.
Antes de datos reales se requiere revisión de privacidad, retención/borrado,
restricción de acceso y pruebas con textos representativos. No hay borrado automático
ni política de retención de producción implementados en esta fase sintética.

## Interfaz

Abrir **Investigación Temática**, escribir tema libre, elegir fuente de prueba,
objetivo/lote y crear. Seleccionar **Iniciar** y ejecutar el trabajador en otra terminal.
Se puede pausar/reanudar/cancelar y consultar registros paginados. La barra expresa
preparados/objetivo, no cobertura de TikTok. Los estados parciales y fallos permanecen
visibles. Salir de la pestaña detiene el sondeo del cliente, no el trabajador.

## Verificación sin servicios externos

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_research*.py' -v
node --test tests/*.cjs
.venv/bin/python -B tests/benchmark_research.py 400
.venv/bin/python -B tests/benchmark_research.py 1000
```

Las pruebas usan un doble Mongo transaccional en memoria: valida operadores usados,
unicidad y rollback, pero no reproduce fallos distribuidos, conflictos reales ni
latencia de Atlas. El navegador usa HTTP local contra FastAPI con ese doble. Ninguna
prueba de investigación de descubrimiento automático crea un cliente real ni consulta TikTok/OpenAI.
La suite opcional de MongoDB real se ejecuta por separado; véase
[Validación MongoDB aislada](mongodb-integration.md).

El benchmark crea un corpus controlado sin cargarlo entero desde el conector. Reporta
tiempo de extremo a extremo con `tracemalloc`, pico de asignaciones Python y pico
RSS del proceso en Linux, que incluye el intérprete/dependencias. El doble copia
estado para simular rollback y realiza búsquedas lineales: sus tiempos no estiman
la instalación MongoDB real. Ejecutar cada tamaño en un proceso separado.

### Resultados de esta entrega

Las 17 pruebas nuevas Python pasan, incluyendo API, recuperación, reservas,
preparación, cargas de 200/400/500/1000 y navegador a 375/768/1280 px. Los cinco
archivos de pruebas JavaScript pasan. La suite de regresión ejecutó 237 pruebas:
cuatro fallos ya identificados (etiquetas de Big Five y tres anchuras de SocialMind)
y una omisión por falta de un snapshot externo; ningún fallo nuevo del módulo.

Una ejecución controlada en Linux/Python 3.12.2, lote 50 y `tracemalloc` activo:

| Objetivo/preparados | Tiempo total | Pico Python | Pico RSS proceso | Lotes |
|---|---:|---:|---:|---:|
| 400/400 | 2,4967 s | 0,784 MiB | 41,367 MiB | 13 |
| 1000/1000 | 14,3432 s | 1,368 MiB | 42,891 MiB | 31 |

Son mediciones individuales del conector/doble, sujetas a variación; no estimaciones
de rendimiento sobre Atlas, red, Chromium o TikTok. Posteriormente se validaron
índices, conflictos, pérdida de conexión y expiración de reservas con MongoDB real
en un replica set local desechable: [resultados y límites](mongodb-integration.md).

## Fuentes de adquisición — Fase 3

El conector YouTube y sus capacidades amplían la implementación sintética descrita
arriba. Configuración, contratos, privacidad y piloto autorizado:
[Adquisición YouTube](youtube-acquisition.md).

## TikTok temático

Se incorpora un adaptador Playwright seleccionable sin variables, con habilitación separada de adquisición externa.
[Recorrido controlado, configuración y límites](tiktok-thematic.md). No se ha
verificado adquisición en TikTok real.
