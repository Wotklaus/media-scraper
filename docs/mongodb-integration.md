# Validación de persistencia y recuperación con MongoDB real

## Entorno y aislamiento (2026-10-29)

Rama `feature/analisis-educativo`, sin cambiar configuración principal, instalar
servicios ni utilizar el URI de `backend/.env`. Se utilizó la imagen Docker
`mongo:8` ya disponible, servidor **8.2.12**, en un contenedor nuevo
`ms-research-it-20261029-d36a9f2b`. Replica set `msIntegration`, un único nodo;
puerto publicado solamente en `127.0.0.1:32768`, sin montajes del host.
`/data/db` y `/data/configdb` son tmpfs desechables de 512/64 MiB;
límites de 1 GiB y 2 CPU, caché WiredTiger 0,25 GiB.

Antes de las escrituras solamente existían las bases administrativas. La ejecución
correcta creó `media_scraper_integration_20261029_e74c1ad9`; el intento inicial usó
otro nombre nuevo (`media_scraper_integration_20261029_d36a9f2b`). Ninguna base
preexistente se reutilizó, modificó o borró. El contenedor MongoDB preexistente
del equipo y las colecciones de Media Scraper quedaron fuera del recorrido.
La auditoría final encontró solamente las cuatro colecciones `research_*` y la
marca de aislamiento: 10 investigaciones y 1922 registros. Después se detuvo el
contenedor nuevo con `--rm`, retirando sus tmpfs; se comprobó que el contenedor
preexistente seguía activo en su puerto original.

El ejecutable `tests/integration_research_mongodb.py` requiere URI explícito y
`--confirm-isolated`; no lee `.env`. Rechaza credenciales, hosts remotos, puerto
27017, otro replica set, nombres ajenos al prefijo de integración y bases ya
existentes. Nunca ejecuta `dropDatabase`. Una marca `_integration_manifest`
documenta el propósito sintético en la base nueva. Tres pruebas unitarias verifican
que estos rechazos ocurran antes de escribir.

## Resultados reales

**9 pruebas, 36,886 s, cero errores y cero fallos**. El contenido es sintético;
las operaciones, transacciones, índices, conflictos y errores de conexión usan
MongoDB/PyMongo reales.

| Escenario | Resultado verificado |
|---|---|
| Persistencia incremental y consulta | Estudios, publicaciones y tareas coherentes; paginación sin solapamiento |
| Índices únicos | El servidor rechaza claves repetidas; no aumentan los registros únicos |
| Rollback | Una inserción dentro de una transacción abortada no permanece |
| Muerte antes del guardado | Subproceso termina con `os._exit(71)`; nuevo trabajador retoma al vencer la reserva |
| Muerte después del guardado y antes del checkpoint | Lote pendiente durable recuperado sin volver a contar registros |
| Reserva sustituida | Token anterior recibe `LeaseLost`; propietario vigente confirma |
| Dos trabajadores | Reserva atómica con un ganador; confirmaciones concurrentes permiten un único commit lógico |
| Cierre de conexión | `failCommand` cierra una conexión durante `update`; reintento transaccional recupera |
| Error al confirmar | `UnknownTransactionCommitResult` en `commitTransaction`; recuperación sin duplicación |
| Página repetida | Registros y contenido iguales; duplicados contabilizados, preparados sin incremento |
| Pausa/reanudación/cancelación | Se revoca la reserva; recuperación y cancelación preservan datos confirmados |

Las dos interrupciones usan procesos realmente terminados y vencimiento de reserva
por tiempo real. El caso específico de sustitución del token adelanta un reloj
controlado; las operaciones y predicados se evalúan en MongoDB real. En concurrencia
se usan clientes independientes y dos hilos.

Se comprueba `received = prepared + duplicates + excluded`, igualdad entre
`prepared` y documentos almacenados, límite del objetivo, unicidad, contadores de
publicaciones y tareas; en `target_reached` no quedan tareas pendientes.

## Rendimiento observado

Lote 50, conector controlado, Linux/Python 3.12.2, `tracemalloc` activo.

| Objetivo/preparados | Recibidos | Excluidos | Duplicados | Lotes | Tiempo total | Pico Python | RSS cliente | Comandos fallidos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 400/400 | 471 | 30 | 41 | 13 | 1,1640 s | 0,067 MiB | 42,953 MiB | 0 |
| 1000/1000 | 1177 | 74 | 103 | 31 | 2,6956 s | 0,069 MiB | 42,953 MiB | 0 |

Ambas investigaciones terminaron en `target_reached`. El tiempo total incluye
creación y procesamiento. El pico Python mide asignaciones trazadas durante cada
carga; RSS es el máximo acumulado del proceso cliente, incluyendo intérprete,
dependencias y casos anteriores. No mide el pico de MongoDB ni memoria incremental
independiente de cada caso. Son ejecuciones individuales, no un estudio de latencia.
Los benchmarks anteriores con dobles en memoria no son comparables directamente.

Recuperación antes del guardado: **10,0843 s** incluyendo vencimiento, **0,0543 s**
de ejecución posterior; después del guardado: **9,9518 s** y **0,0212 s**,
respectivamente. Ambos llegaron a 73 preparados. El cierre de conexión y posterior
recuperación midió **0,492 s**; el escenario completo registró dos comandos fallidos
inyectados (conexión y commit), sin pérdida ni duplicación final.

## Incidencias y alcance

El primer intento falló al construir índices: el mínimo predeterminado de espacio
libre (500 MiB) era incompatible con el tmpfs de 512 MiB después de inicializar
WiredTiger. Se ajustó **solamente el servidor temporal** mediante
`indexBuildMinAvailableDiskSpaceMB=64` y se repitió con una base nueva. No fue un
defecto del repositorio. No fueron necesarias correcciones al código de producción.

Regresión: **240 pruebas Python en 29,933 s**, cuatro fallos conocidos y una
omisión por snapshot externo ausente. Se verificaron los nombres de los fallos:
`test_dashboard_grid_navigation_statistics_and_errors` (etiquetas Big Five), y
`test_responsive_navigation_and_read_only_states` (SocialMind) a 1440/1024/390 px.
Coinciden con la línea base; no apareció un fallo nuevo de investigación. Los
cinco archivos JavaScript pasaron. `git diff --check` no detectó errores.

No se verificaron elecciones entre nodos, caída/reinicio del servidor, pérdida
física de almacenamiento, Atlas, latencia WAN ni capacidad de TikTok. La reserva
depende del reloj de aplicación: deben evitarse desviaciones importantes entre
trabajadores. Las pruebas acreditan los escenarios descritos, no procesamiento
exactamente una vez en la red ni durabilidad ante cualquier fallo.

## Reproducción optativa

Usar exclusivamente un contenedor desechable nuevo, sin volúmenes del host:

```bash
docker run --detach --rm --name ms-research-integration \
  --publish 127.0.0.1::27017 \
  --tmpfs /data/db:rw,nosuid,nodev,size=512m \
  --tmpfs /data/configdb:rw,nosuid,nodev,size=64m \
  --memory 1g --cpus 2 --security-opt no-new-privileges \
  mongo:8 mongod --replSet msIntegration --bind_ip_all \
  --wiredTigerCacheSizeGB 0.25 --setParameter enableTestCommands=1 \
  --setParameter indexBuildMinAvailableDiskSpaceMB=64
docker exec ms-research-integration mongosh --quiet --eval \
  'rs.initiate({_id:"msIntegration",members:[{_id:0,host:"127.0.0.1:27017"}]})'
docker port ms-research-integration 27017/tcp
```

Esperar a que el nodo sea primario. Sustituir `PUERTO` por el puerto publicado;
el nombre de base se genera de forma única si no se proporciona:

```bash
.venv/bin/python -B tests/integration_research_mongodb.py \
  --uri 'mongodb://127.0.0.1:PUERTO/?replicaSet=msIntegration&directConnection=true' \
  --confirm-isolated
```

No habilitar `enableTestCommands` ni failpoints en un servidor compartido o de
producción. El ejecutable imprime entorno, resultados y métricas; no guarda secretos
ni cuerpos de comandos. Al terminar, detener **solamente el contenedor creado**:
`docker stop ms-research-integration`. `--rm` y tmpfs eliminan sus datos temporales.
La suite normal `unittest discover -s tests` no ejecuta esta integración opcional.

Antes de conectar una fuente externa: verificar autorización y contrato de la
fuente, paginación y procedencia mediante respuestas controladas; después realizar
un piloto limitado en almacenamiento aislado. Esta validación no autoriza ni prueba
adquisición externa.
