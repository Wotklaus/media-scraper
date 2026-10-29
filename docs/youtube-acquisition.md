# Fase 3: adquisición temática con YouTube Data API v3

## Alcance

Se implementa exclusivamente adquisición. No se añaden embeddings, clustering,
recomendaciones, afiliaciones ni proveedores comerciales. El tema sigue siendo
texto libre. Cada estudio selecciona una única fuente; sus registros no se mezclan.
TikTok por username conserva su motor y sus contratos. TikTok temático está
identificado como no habilitado, sin automatizar búsquedas protegidas.

## Arquitectura

`research_routes` valida `StudyCreate` y persiste una investigación en borrador.
Solo Inicio/Reanudar encola procesamiento. El comando independiente
`backend.manage research-worker` obtiene reservas, selecciona el conector en
`research_sources.connector_for` y ejecuta `read` fuera de las transacciones.
`research_youtube.YouTubeConnector` realiza exclusivamente GET a
`https://www.googleapis.com/youtube/v3/` mediante biblioteca estándar; no hay SDK
ni dependencias nuevas. El transporte puede sustituirse por respuestas controladas.

Operaciones oficiales:

- [`search.list`](https://developers.google.com/youtube/data/reference/rest/v3/search/list): `q` libre, `type=video`, páginas de hasta 50; periodo opcional de publicación del video.
- [`videos.list`](https://developers.google.com/youtube/data/reference/rest/v3/videos/list): descripción, título, fecha y métricas disponibles. Una métrica ausente no se convierte en cero.
- [`commentThreads.list`](https://developers.google.com/youtube/data/reference/rest/v3/commentThreads/list): comentarios principales, texto plano y orden temporal.
- [`comments.list`](https://developers.google.com/youtube/data/reference/rest/v3/comments/list): respuestas opcionales por `parentId`, con paginación propia. No se supone que las respuestas incluidas en un hilo sean completas.

Los tokens se guardan en un cursor JSON con versión `v=1`, además de la versión del conector en cada documento.
En modo respuestas se solicita un hilo por página; el cursor conserva el ID del
comentario padre, token de respuestas y siguiente página de hilos. Esto mantiene
memoria acotada y permite reanudar sin almacenar una página de autores. Es más
costoso en solicitudes; está deshabilitado de forma predeterminada.

La adquisición conserva la relevancia proporcionada por búsqueda de YouTube;
no hay evaluación semántica adicional ni garantía de pertinencia científica.
No se descargan subtítulos, transcripciones ni contenido audiovisual.

## Configuración

Configurar `YOUTUBE_API_KEY` en el entorno **del servidor FastAPI y del trabajador**
mediante el mecanismo seguro local utilizado por el operador. Este módulo no lee
la clave de `backend/.env` ni la acepta en solicitudes o `source_config`. No se ha
creado ni modificado configuración local con secretos. Restringir la clave a
YouTube Data API v3 y al entorno autorizado. Se envía mediante `X-Goog-Api-Key`,
no en la URL; no se registra ni persiste, siguiendo las
[recomendaciones de Google](https://docs.cloud.google.com/docs/authentication/api-keys-best-practices).

La presencia de la variable indica configuración disponible, no valida la clave,
el permiso ni la cuota. `/api/research/sources` no contacta al proveedor.

```bash
.venv/bin/python -m uvicorn backend.main:app --reload
.venv/bin/python -m backend.manage research-worker
```

Se conserva la conexión MongoDB existente y su requisito de transacciones mediante
replica set/Atlas. No se introducen colecciones ni índices adicionales. Para un
piloto usar una instalación de pruebas aislada; no cambiar datos históricos.

## Contrato HTTP y uso

Se amplían rutas existentes; no se añaden rutas de análisis:

- `GET /api/research/sources`: conserva campos sintéticos previos y añade `sources`
  con disponibilidad, capacidad de descubrimiento, comentarios, respuestas y motivo
  de indisponibilidad. TikTok temático aparece deshabilitado.
- `POST /api/research/studies`: admite `source: "youtube"` y configuración específica.
  Devuelve 503 si falta clave y 422 ante configuración inválida o de otra fuente.
- Listado, detalle, progreso, inicio, pausa, reanudación, cancelación, publicaciones,
  tareas y registros mantienen las rutas `/api/research/studies/...` existentes.

Ejemplo de cuerpo (creación por sí sola no adquiere datos):

```json
{
  "topic": "Tema libre elegido por el usuario",
  "source": "youtube",
  "target_records": 400,
  "limits": {"batch_size": 50, "lease_seconds": 60, "time_budget_seconds": 300},
  "source_config": {
    "max_publications": 20,
    "max_pages_per_publication": 20,
    "include_replies": false,
    "published_after": null,
    "published_before": null
  }
}
```

Máximo 200 publicaciones y 200 páginas por publicación; cada página de comentarios
admite hasta 100 elementos. Estos topes limitan trabajo, no garantizan cobertura.
El objetivo cuenta exclusivamente preparados válidos y únicos. El periodo usa
fechas RFC3339 con zona horaria y se aplica a videos, no a comentarios. Una cota
máxima de páginas puede terminar una tarea antes de agotar el proveedor: el campo
`source_complete` queda falso si se alcanza el límite de páginas; no acredita
totalidad de YouTube. `exhausted` tampoco implica haber revisado todos los resultados posibles.

En Investigación Temática seleccionar YouTube, configurar objetivo y límites,
crear y después iniciar. Se muestran fuente, progreso, recibidos, preparados,
excluidos, duplicados, publicaciones y errores. Abrir la sección no inicia trabajos.
La fuente sintética mantiene el aviso **Datos de prueba — No reales**.

## Persistencia y recuperación

Se reutilizan `research_studies`, `research_tasks`, `research_publications` y
`research_records`. Se mantienen índices únicos, reservas con tokens, transacciones
con write concern majority y confirmación diferida del checkpoint. Una página
persistida pendiente se confirma sin volver a llamar al proveedor. Una interrupción
antes de guardarla puede repetir la petición y consumir cuota de nuevo; no se
promete exactamente una vez a nivel de red. Tokens vencidos o resultados que
cambian pueden impedir reproducir una página: se informa error, sin inventar datos.

Publicaciones conservan ID de video, fuente, título/descripción preparados,
fecha disponible, métricas, fecha de descubrimiento y `acquisition_version`.
Los registros conservan clave HMAC limitada al estudio, ID de publicación, texto
preparado, fecha disponible, tipo comentario/respuesta y versión del adaptador.
Se rechazan comentarios vacíos o mayores de 4000 caracteres; las descripciones
admiten hasta 10000 antes de prepararse. Los documentos antiguos siguen siendo legibles con valores opcionales por defecto.
No se migran ni reescriben datos históricos.

## Errores, cuotas y límites

Timeout HTTP de 10 s, respuesta acotada a 2 MB y tamaño de lote validado antes de
persistir. HTTP 429/5xx y errores de red producen reintentos limitados con la espera
existente. `commentsDisabled` falla la tarea del video y permite resultados parciales.
Cuota agotada, credenciales ausentes o acceso denegado **pausan** el estudio,
conservando cursor y tarea para reanudación explícita tras corregir la causa.
Errores HTTP contienen solamente códigos locales permitidos; no cuerpos del
proveedor, URLs con claves ni texto original. Se conserva el presupuesto de tiempo
activo y la pausa/cancelación entre lotes; una petición en curso no se cancela.
Usar reserva predeterminada de 60 s para cubrir las solicitudes de descubrimiento.

No se calcula una cuota universal fija: consultar los límites actuales del proyecto
en Google Cloud y la documentación oficial. Las páginas y reintentos consumen cuota;
los límites locales no equivalen a un presupuesto diario compartido entre estudios.
No se rotan claves ni se eluden restricciones.

## Privacidad y condiciones pendientes para despliegue

Solo se proyectan campos necesarios del proveedor: no se conservan nombre del
comentarista, canal del autor, avatar ni URL de perfil. El texto pasa por las reglas
existentes para correos, teléfonos, menciones, URLs e identificadores evidentes.
Los IDs de comentarios no se guardan en registros analíticos; un ID padre puede
permanecer temporalmente en el cursor para paginar respuestas. No es identidad de
comentarista, pero permite vincular contenido público y requiere control de acceso.

La eliminación de identificadores no impide reidentificación por texto, contexto,
nombres propios o búsqueda literal. La preparación también puede suprimir números
legítimos. No se afirma anonimización irreversible. Tema y descripción del estudio
son texto del operador y no deben incluir datos personales.

Antes de una explotación pública/comercial deben resolverse política de privacidad,
consentimiento/avisos aplicables, acceso al servicio y procedimientos de retención,
actualización y eliminación conforme a las
[políticas de YouTube](https://developers.google.com/youtube/terms/developer-policies).
Esta fase no incorpora mantenimiento automático de retención ni acredita cumplimiento
integral. No usar indefinidamente el corpus sin revisar esas obligaciones.

## Pruebas y primera adquisición autorizada

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_research_youtube.py' -v
.venv/bin/python -B -m unittest discover -s tests
node --test tests/*.cjs
```

Las pruebas usan transporte controlado y doble Mongo transaccional; no consultan
YouTube, OpenAI ni MongoDB existente. Cubren configuración, texto libre, búsqueda,
metadatos, paginación, respuestas, procedencia, preparación, deduplicación, errores,
credenciales, pausa por cuota, endpoints, cargas de 400/1000 y recuperación después
del guardado. La prueba de navegador selecciona YouTube contra HTTP local y
bloquea solicitudes fuera del servidor de pruebas. Aunque los objetos del contrato
usan `synthetic=false` para probar la rama YouTube, todos sus contenidos son fixtures.

Validación final: 252 pruebas Python en 35,435 s; 247 satisfactorias, cuatro
discrepancias previas (Big Five y SocialMind a tres anchuras) y una omisión por
snapshot externo ausente. Las 11 pruebas nuevas del conector y la nueva prueba de
navegador pasaron, incluyendo cargas de 400 y 1000 preparados y recuperación.
Los cinco archivos de pruebas JavaScript pasaron; `git diff --check` sin errores.
No se atribuyen estas cargas controladas al rendimiento de YouTube real.

La validación MongoDB real anterior se documenta en `mongodb-integration.md`;
no constituye una ejecución real del nuevo adaptador ni se repitió en esta fase.
No se ejecutó adquisición real ni se validaron credenciales/cuotas del operador.

Para el primer piloto, **después de autorización explícita**:

1. Habilitar YouTube Data API v3 en el proyecto autorizado y configurar la clave en
   ambos procesos, sin guardarla en Git ni enviarla al navegador.
2. Acreditar una base de pruebas aislada y revisar condiciones de acceso y retención.
3. Crear desde la interfaz un estudio YouTube de 20 registros, pocos videos,
   respuestas desactivadas y límites reducidos. Revisar el tema y el alcance.
4. Iniciar expresamente y ejecutar el trabajador. Verificar procedencia, métricas,
   privacidad, contadores, paginación y estados; comparar con disponibilidad real.
5. Probar pausa/reanudación y aumentar gradualmente a 400/1000 solo si cuota y
   cobertura lo permiten. Conservar resultados parciales; no completar con fixtures.

La siguiente fase podrá leer texto y referencias existentes para inteligencia
semántica sin volver a adquirir innecesariamente. No se crean sus colecciones ni
contratos todavía; la relevancia futura debe mantenerse separada de afiliación.
