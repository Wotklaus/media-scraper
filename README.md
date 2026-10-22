# Media Scraper

Extracción de información pública de TikTok con FastAPI, Playwright y JavaScript.

## Preparación

Desde la raíz del proyecto, con el entorno `.venv` y las dependencias instaladas:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

El bloqueo de sesión usa `fcntl.flock`, disponible en Linux (el entorno de este proyecto). No requiere dependencias adicionales.

## Configurar la sesión inicial

En una terminal con escritorio gráfico disponible:

```bash
.venv/bin/python -m backend.manage session
```

Se abre Chromium visible con un perfil **exclusivo de Media Scraper**. Inicia sesión manualmente en tu propia cuenta de TikTok. Si aparece una verificación, resuélvela manualmente o cancela con Ctrl+C en la terminal. Cuando hayas terminado, pulsa ENTER en la terminal: se cierra Chromium y el contexto persistente guarda el estado. El mensaje de guardado no certifica que TikTok haya aceptado la autenticación.

La aplicación reutiliza `.media-scraper/chromium/` entre consultas y reinicios mediante `launch_persistent_context`. No usa perfiles personales de Chrome o Brave ni exporta cookies. TikTok puede vencer o revocar la sesión: vuelve a ejecutar el comando de configuración si lo solicita. No se automatizan CAPTCHA ni se eluden restricciones.

Solo puede usar el perfil un proceso a la vez. Si la configuración está abierta o ya hay una consulta en curso, otra consulta real recibe un mensaje de sesión ocupada. El bloqueo se libera al cerrar el proceso; no borres `session.lock` mientras haya procesos activos.

## Arrancar la aplicación

```bash
bash start.sh
```

Abre <http://127.0.0.1:8000>. También puedes arrancarla desde la raíz con:

```bash
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

La ejecución normal no imprime perfiles ni avisos de extracción parcial. Los avisos se conservan en `_meta.warnings` de la respuesta. Para consultar los detalles técnicos y el perfil público en consola, inicia explícitamente con DEBUG:

```bash
.venv/bin/python -c 'import logging; import uvicorn; logging.basicConfig(level=logging.DEBUG); uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, access_log=False)'
```

Selecciona **Consulta real**, introduce un username y pulsa **Analizar perfil**. Las consultas usan Chromium headless: no abren ventanas. Se mantienen el dashboard, las estadísticas, los detalles y la paginación de hasta diez videos. Solo se muestran los videos que TikTok permita obtener; no se inventan elementos para completar diez.

FastAPI ejecuta el scraper síncrono en su grupo de hilos y el frontend espera mediante `fetch`, sin bloquear la interfaz. No hay una cola de trabajos ni consultas periódicas. La espera del frontend es de hasta diez minutos, porque los videos se procesan en serie. Si se cierra la pestaña o vence esa espera, el scraper puede continuar hasta terminar y cerrar Chromium; mientras tanto, la sesión sigue bloqueada.

El origen y los avisos de datos parciales aparecen sobre el dashboard. Los errores de login, verificación, carga y sesión ocupada se muestran en pantalla. Los errores individuales de videos no eliminan los demás resultados. Las listas de usuarios y comentarios conservan el comportamiento de extracción existente y sus limitaciones; esta implementación no añade acceso a contenido restringido.

## Guardar una captura real autorizada

Con autorización para consultar y guardar los datos públicos del perfil, y sin otra consulta usando la sesión:

```bash
.venv/bin/python -m backend.manage capture USERNAME --authorized
```

Sustituye `USERNAME` por el usuario autorizado, sin una URL. Este comando hace **una nueva consulta real headless** y guarda `.media-scraper/captures/username.json`. No importa archivos de autenticación ni transforma las pruebas sintéticas en capturas. Revisa los avisos: una captura puede contener menos videos o métricas no disponibles si TikTok restringió la consulta.

No se sobrescriben capturas existentes. Para renovarla, renombra primero la captura anterior dentro de esa carpeta y vuelve a ejecutar el comando. No es necesario cerrar FastAPI si no hay una consulta real activa.

Se guardan únicamente los campos del dashboard, hasta diez videos y hasta diez comentarios por video, con fecha UTC y procedencia real. Se omiten campos ajenos a la respuesta pública, URLs firmadas de imágenes y parámetros de seguimiento. Por ello, en demostración el avatar y las miniaturas muestran sus marcadores de respaldo; los títulos, métricas, comentarios y enlaces de videos se conservan.

## Probar ambos modos

1. En **Consulta real**, busca un perfil autorizado. Debe aparecer `CONSULTA REAL`, sin abrir ventanas, con los datos que TikTok permita consultar.
2. Guarda una captura con el comando anterior.
3. Selecciona **Demostración**, busca el mismo username y verifica el indicador `DEMOSTRACIÓN`, la fecha de captura, las estadísticas y la paginación.
4. En demostración, busca un username sin captura: debe informar que no existe una captura, sin consultar TikTok.
5. Si falla el modo real, cambia tú mismo a demostración. No existe cambio automático entre fuentes.

La API conserva los campos anteriores y añade `_meta` para origen, fecha (en demostración) y avisos:

- `GET /api/profile/USERNAME` o `?mode=real`: consulta real.
- `GET /api/profile/USERNAME?mode=demo`: captura local del mismo username.
- Un modo desconocido devuelve 422; captura inexistente, 404; sesión ocupada, 409; fallo de TikTok, 502; fallo de acceso a datos locales, 503.

## Privacidad

`.media-scraper/` está excluida de Git y fuera de los archivos públicos servidos por FastAPI. Sus directorios privados tienen permisos 700; los archivos de bloqueo y capturas, 600. El perfil del navegador queda protegido por su carpeta privada. Las capturas también pueden contener nombres y comentarios: revisa su contenido antes de compartirlas. No publiques esta aplicación local como un servicio público con tu sesión personal.

No se registran cookies, contraseñas ni respuestas de autenticación. Los errores de Playwright se sustituyen por mensajes controlados. No se activa HAR, trazado ni grabación de navegador. El extractor de consola histórico `main.py` se conserva como herramienta independiente; usa la aplicación web o `backend.manage` para este nuevo flujo persistente.

## Pruebas

```bash
.venv/bin/python -B -m unittest discover -s tests -v
```

Las pruebas no consultan TikTok. Usan datos sintéticos y directorios temporales, que no se instalan como demostraciones. Cubren selección por ID, JSON alternativos, restricciones, bloqueo entre procesos, modos de API, capturas sin credenciales, compatibilidad de campos y diez videos. Dos pruebas abren Chromium **headless** para comprobar persistencia de una cookie de prueba y localStorage, así como selector de modos, indicadores, estadísticas, detalles y paginación del dashboard. Requieren Chromium instalado.

Una consulta real sigue siendo necesaria para confirmar la validez de tu sesión, los selectores y JSON actuales de TikTok, los diez videos de un perfil con suficientes publicaciones accesibles, las cinco métricas, seguidores/seguidos/comentarios disponibles, rendimiento y solicitudes reales de verificación. La persistencia no garantiza que TikTok permita acceso headless ni elimina CAPTCHA.

Se emplea la API oficial [launch_persistent_context](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context); el estado de autenticación es sensible, como indica la [documentación de autenticación de Playwright](https://playwright.dev/python/docs/auth).

## Embeddings de publicaciones almacenadas

Este módulo consulta MongoDB sin ejecutar el scraper. Requiere `OPENAI_API_KEY`
en `backend/.env` y usa `text-embedding-3-small` con 1536 dimensiones mediante
el [SDK oficial de OpenAI](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create).
La clave no se devuelve ni se registra. Solo se envía la descripción textual;
los comentarios, métricas e identificadores permanecen fuera de la solicitud a OpenAI.

- `POST /api/embeddings/USERNAME?limit=10`: **genera con costo** únicamente cuando
  se invoca explícitamente. No se ejecuta al arrancar ni al consultar TikTok.
  `limit` admite valores de 1 a 10. Selecciona publicaciones por `publication_id`
  descendente; el límite incluye descripciones vacías, que se omiten sin llamar a OpenAI.
- `GET /api/embeddings/USERNAME?limit=10`: consulta los últimos embeddings
  almacenados (incluye vectores e historial de textos/modelos), sin generarlos.
- `GET /api/embeddings/USERNAME/similarity?first_id=ID1&second_id=ID2`:
  calcula similitud coseno entre dos publicaciones del perfil usando sus
  descripciones actuales y el modelo configurado. Si faltan embeddings vigentes,
  devuelve 404; nunca los genera como efecto de la consulta.

La respuesta de generación contiene `processed`, `generated`, `reused`, `failed`,
`skipped` y `results` con el estado por publicación. Los errores individuales
se cuentan sin exponer detalles del proveedor. Un perfil inexistente devuelve
404, un límite inválido 422 y un fallo general de MongoDB 503.

La colección `embeddings` conserva `publication_id`, `profile_username`, `text`,
`model`, `vector`, `content_hash` (SHA-256 del texto sin espacios exteriores) y
`generated_at` (UTC). Un índice único por publicación, modelo y hash y una
inserción atómica evitan documentos duplicados. Si cambia el texto, se conserva
el vector anterior como historial. Las solicitudes sucesivas reutilizan el
documento sin llamar a OpenAI. Solicitudes simultáneas podrían llamar al proveedor
antes de detectar la inserción concurrente; el índice garantiza un solo documento.
El SDK tiene reintentos automáticos desactivados y timeout de 30 segundos.

Pruebas unitarias del módulo, con OpenAI y MongoDB simulados y sin Chromium:

```bash
.venv/bin/python -m unittest discover -s tests -p test_embeddings.py -v
```

## Espacio Big Five por perfil almacenado

Big Five permite elegir cualquier perfil guardado por nickname y username. Al
entrar desde General, selecciona el perfil visible si existe en MongoDB. Cambiar
de selección consulta solo datos almacenados y limpia los resultados de la vista
anterior; las respuestas atrasadas no pueden reemplazar la selección actual.

Se añaden únicamente dos endpoints de lectura:

- `GET /api/stored-profiles`: usernames, nicknames e identificadores normalizados.
- `GET /api/stored-profiles/USERNAME/publications`: publicaciones almacenadas,
  metadatos del embedding vigente por publicación, conteos y los cinco pares más
  relacionados mediante similitud coseno. No devuelve los vectores completos.

Los conteos distinguen publicaciones disponibles, embeddings vigentes, pendientes
y descripciones vacías. Un vector solo es vigente si coincide el perfil, la
publicación, el hash de la descripción y el modelo; además debe ser válido y tener
1536 dimensiones. Los historiales no inflan los indicadores. La generación sigue
procesando las primeras diez publicaciones por ID descendente; la vista indica
cuántas están pendientes dentro de ese grupo y cuántas existen en total. Solo el
botón **Generar embeddings** invoca el POST con costo; navegar y cambiar de perfil
no generan embeddings ni consultan TikTok.

La evaluación Big Five conserva un módulo independiente con estado sin evaluación.
Las similitudes semánticas no se convierten en puntuaciones de personalidad.

Pruebas adicionales sin servicios externos ni Chromium:

```bash
.venv/bin/python -m unittest discover -s tests -p test_stored_profiles.py -v
node tests/test_big_five.cjs
```

## Dashboard semántico de Big Five

La vista conserva el selector de perfiles y añade indicadores grandes, mapa SVG
interactivo, panel de generación, cinco pares relacionados, temas con evidencias,
interpretación breve y cinco dimensiones psicométricas vacías hasta disponer de
un cuestionario válido. Los estilos del rediseño están limitados a `#big-five`;
General y Estadísticas conservan su presentación.

Nuevos endpoints (las rutas existentes permanecen disponibles):

| Método y ruta | Resultado |
| --- | --- |
| `GET /api/semantics/USERNAME/map` | Coordenadas PCA, varianza conservada y cinco pares por coseno exacto, con descripciones abreviadas y enlaces originales. |
| `GET /api/semantics/USERNAME/analysis` | Interpretación vigente almacenada, o estado `empty`/`stale` sin hallazgos obsoletos. |
| `POST /api/semantics/USERNAME/analysis` | Generación explícita de interpretación o reutilización del mismo conjunto de textos. Tiene costo solo si se consulta al proveedor. |
| `GET /api/semantics/USERNAME/big-five` | Evaluación de cuestionario validado o `unavailable`, sin puntuaciones. |

El endpoint del mapa incluye los pares relacionados para evitar una ruta y una
lectura duplicadas. Reutiliza `EmbeddingRepository` y `cosine_similarity`.
Selecciona las primeras diez publicaciones por `publication_id` descendente y
admite únicamente vectores vigentes de `text-embedding-3-small` con 1536 dimensiones.
La PCA centra los vectores y diagonaliza su matriz de Gram con Jacobi en Python;
no necesita NumPy, coordenadas aleatorias ni librerías gráficas. Devuelve
`points`, `explained_variance_ratio` y `rank`. Un único vector queda en el origen;
dos vectores generan solo dos puntos. Los vectores idénticos se superponen y se
pueden seleccionar individualmente con los botones numerados. La distancia en
dos dimensiones no equivale a la similitud coseno en 1536 dimensiones.

La interpretación usa `gpt-5.4-mini-2026-03-17`, razonamiento `none`, hasta 6000
tokens de salida y [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
mediante `client.responses.create` con JSON Schema estricto y Pydantic. Primero se
comprueba el estado de la respuesta y después se valida el JSON. La compatibilidad del modelo está
documentada en [OpenAI Docs](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
Solo se envían descripciones válidas e IDs de respaldo (máximo diez publicaciones,
24000 caracteres en total); nunca usernames, métricas, comentarios ni vectores.
La clave se lee exclusivamente en el backend mediante el cliente ya existente.
No se ejecutan reintentos automáticos ni peticiones al cargar o cambiar de perfil.

`semantic_analyses` conserva `profile_id`, hash del conjunto de IDs/textos, modelo,
versión del prompt, IDs analizados, fecha UTC e interpretación. Esta contiene
`summary`, `themes` y `communication_style`, con referencias y citas literales.
Se rechazan IDs externos, citas que no aparecen en el texto, respuestas incompletas,
rechazos del modelo y campos fuera del esquema. La validación de referencias no
convierte una interpretación generada en una clasificación objetiva.

Un `_id` determinista reserva el conjunto antes de llamar a OpenAI: los POST
sucesivos reutilizan el resultado y los concurrentes reciben 409 si sigue en curso.
Un error controlado permite reintentar manualmente el mismo registro sin duplicarlo.
Si el proceso termina abruptamente, la reserva `processing` requiere revisión
administrativa antes de reintentar; no se libera automáticamente para evitar
llamadas potencialmente duplicadas. Los fallos de generación/validación devuelven
502, los textos vacíos o excesivos 422, perfil inexistente 404 y acceso a MongoDB 503.

El lector de `big_five_evaluations` prepara un contrato para una futura importación
confiable de cuestionarios: `profile_username`, `source=validated_questionnaire`,
`status=validated`, `instrument` con `name` (`BFI-2`, `NEO-PI-R` o `IPIP-NEO-120`) y
`version`, `scoring_version`, `completed_at` como fecha BSON, `scale={min:0,max:100}`
y `scores` con las cinco claves `openness`, `conscientiousness`, `extraversion`,
`agreeableness`, `neuroticism`, todas finitas en esa escala. Estos metadatos deben
proceder de un proceso externo de validación; este cambio no administra, puntúa,
valida científicamente ni importa cuestionarios. Nunca escribe evaluaciones ni
usa OpenAI/TikTok para crearlas. Si falta ese contrato, no entrega puntuaciones
y el apartado del cuestionario no crea barras rellenas ni medidores.

Pruebas adicionales con fixtures sintéticas, sin Chromium ni servicios externos:

```bash
.venv/bin/python -m unittest discover -s tests -p test_semantics.py -v
node tests/test_semantic_dashboard.cjs
```

Las pruebas de interfaz usan un DOM mínimo en memoria: verifican SVG, puntos,
selección, enlaces, descripciones abreviadas, módulos vacíos, errores y respuestas
atrasadas de perfiles anteriores. El diseño incluye cortes a 1000 y 650 píxeles,
SVG con `viewBox`, columnas flexibles y controles accesibles mediante teclado.
La apariencia visual en un navegador real no se verifica con Chromium en esta tarea.

## Acciones manuales, diagnóstico y señales lingüísticas OCEAN

Hay tres botones independientes: **Generar embeddings**, **Analizar contenido con
OpenAI** y **Analizar Big Five**. Abrir la aplicación, navegar o elegir perfiles
solo ejecuta GET. El scraper y la persistencia de extracción no invocan estos
servicios. Con cero embeddings pendientes, el botón muestra **Todos los embeddings
están generados**, permanece deshabilitado y reutiliza los vectores existentes.
No se eliminaron ni regeneraron los vectores de perfiles reales durante este cambio.

Se reprodujo un defecto con OpenAI SDK 3.36.1 y transporte HTTP en memoria:
`responses.parse()` lanza `ValidationError` al recibir un JSON truncado aunque
el estado sea `incomplete`. La comprobación posterior de `response.status` no
llegaba a ejecutarse. El `except Exception` anterior ocultaba esa causa, igual
que cualquier error de credenciales, modelo, validación o persistencia. No había
un registro técnico de los intentos históricos: el mensaje genérico observado
en Brave no permite confirmar cuál de esas causas ocurrió en ese intento.

La corrección usa `responses.create` manteniendo Structured Outputs estricto;
comprueba `status`, `incomplete_details` y rechazos antes de interpretar JSON.
Los esquemas y las citas se siguen validando y no se reparan ni reintentan con
otra llamada pagada. El límite de salida sube a 6000 tokens y el prompt pide
citas más cortas para reducir respuestas truncadas. No se cambió el modelo.

Los fallos devuelven `detail={code,message,reference}`. Los registros del servidor
incluyen referencia, etapa, categoría, modelo, tipo de excepción, estado HTTP y
solo códigos/parámetros del proveedor permitidos. No incluyen claves, usernames,
descripciones, cuerpo de error, respuestas completas ni tracebacks. Cuando se
puede acceder a MongoDB, se conserva el diagnóstico seguro en `failure` del
registro fallido; GET puede mostrarlo sin consultar OpenAI. Un fallo histórico
sin diagnóstico se identifica como tal. Los límites de cuota devuelven 429,
timeout 504, autenticación/configuración/persistencia 503 y otros fallos de
proveedor o validación 502. No se hace ninguna comprobación pagada de acceso al modelo.

El nuevo módulo **Big Five · Señales lingüísticas** no es una evaluación de la
persona ni un test psicométrico. Conserva el cuestionario independiente en un
desplegable. Solicita indicadores observables del lenguaje, descripciones breves,
IDs reales y citas exactas para cada dimensión OCEAN; rechaza puntuaciones o
porcentajes propuestos por el modelo, IDs externos y evidencias inventadas.

Endpoints adicionales:

- `GET /api/semantics/USERNAME/ocean`: resultado exploratorio vigente, o estado
  vacío, obsoleto, en curso o fallido. Nunca llama a OpenAI.
- `POST /api/semantics/USERNAME/ocean`: genera bajo demanda o reutiliza lo vigente.
  El cuerpo opcional admite `regenerate` y `confirm_cost` (booleanos estrictos).
  Regenerar exige ambos en `true`; la interfaz solicita confirmación del costo.

`ocean_analyses` está separado de `semantic_analyses`, `embeddings` y
`big_five_evaluations`. La identidad incluye perfil, conjunto de IDs/textos,
modelo y versión del prompt. Se preserva el resultado anterior durante la
regeneración y, al completarse, se conserva una revisión con `revision_of`.
Los fallos no borran el resultado anterior ni disparan reintentos. Solicitudes
concurrentes no duplican llamadas para el mismo conjunto.

Cada dimensión contiene `dimension`, `name`, `description`, `indicators`,
`publication_ids`, `support_count`, `total_count`, `status` y `presence_index`.
El servidor calcula el índice como `100 × IDs únicos respaldados / descripciones
válidas analizadas`; nunca cuenta varias veces la misma publicación. Si hay
menos de dos publicaciones de respaldo, `presence_index=null` y el estado es
`insufficient_evidence`: se muestra **Evidencia insuficiente**, sin barra rellena.
Este umbral es una regla de visualización y no una validación psicométrica.
La selección se limita a las primeras diez publicaciones almacenadas y un máximo
de 24000 caracteres. No se envían comentarios, usernames ni vectores al modelo.

Verificación manual en Brave:

1. Seleccionar un perfil con todos sus embeddings vigentes: aparece el estado
   completo y no se emite ningún POST. Cambiar de pestaña/perfil tampoco lo emite.
2. Pulsar **Analizar contenido con OpenAI** solo si se desea autorizar esa
   solicitud pagada. Un error muestra su categoría y referencia correlacionable
   con el registro técnico seguro del servidor.
3. Pulsar **Analizar Big Five** para autorizar el análisis exploratorio. Revisar
   indicadores y citas en cada dimensión; distinguir presencia de señales de una
   puntuación psicológica. Volver al perfil reutiliza lo almacenado mediante GET.
4. Pulsar **Regenerar análisis · Tiene costo**: cancelar no solicita nada; aceptar
   envía el POST con confirmación. Cambiar de perfil durante el proceso no mezcla
   los resultados.

Pruebas de regresión y SDK con transporte simulado, sin red ni Chromium:

```bash
.venv/bin/python -m unittest discover -s tests -p test_ocean.py -v
.venv/bin/python -m unittest discover -s tests -p test_semantics.py -v
node tests/test_big_five.cjs
node tests/test_semantic_dashboard.cjs
```
