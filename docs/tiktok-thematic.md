# TikTok temático mediante Playwright — recorrido controlado

## Estado y permisos

El adaptador existe y está integrado, pero **no se ha ejecutado contra TikTok real**.
Las pruebas interceptan todas las solicitudes de Chromium con HTML/JSON controlado.
Su resultado no acredita que los selectores, estructuras, volúmenes o acceso sean
válidos actualmente en TikTok. No se utiliza TikTok Research API.

TikTok está disponible técnicamente en el selector y permite crear estudios sin
variables de habilitación. La antigua variable de referencia de permiso ya no se
utiliza. Las pruebas locales que sustituyen el recolector tampoco necesitan
variables de adquisición.

La ejecución externa se controla por separado: el recolector real comprueba
`MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED=1` en el entorno **del trabajador**, antes de
abrir Chromium. Sin esa habilitación, Inicio encola el estudio (HTTP 202); cuando
el trabajador lo recoge, queda pausado con `source_permission_missing`, sin abrir
navegador ni realizar solicitudes. Si no hay trabajador activo permanece en cola.
Con habilitación, el trabajador ejecuta el adaptador existente; conserva los
controles de CAPTCHA, autenticación, errores HTTP y procedencia. No requiere una
segunda variable ni se habilita adquisición por seleccionar la fuente.

Esta habilitación operativa no concede autorización de la plataforma. El operador
debe comprobar las condiciones aplicables antes de ejecutar adquisición externa.
No se ha realizado scraping externo durante esta corrección.

## Integración y componentes reutilizados

`research_tiktok.TikTokConnector` implementa el contrato `read` del registro de
fuentes. Su flujo es:

1. Verificar la habilitación antes de iniciar navegador.
2. Abrir el perfil persistente mediante `reference_runtime.persistent_playwright`
   y `_setup_context` del **motor activo** `vendor.scrapingtiktok.TikTokScraper`.
   Se conserva el bloqueo de perfil de `session.py` y se libera el contexto al salir,
   incluso ante timeout o excepción. No se usa el scraper heredado `backend/scraper.py`.
3. Descubrimiento: navegar a `/search?q=<tema codificado>` mediante Chromium,
   inspeccionar enlaces de resultados y rehidratación soportada, desplazar la página
   mediante rueda y detenerse al observar suficientes candidatos o alcanzar límites.
4. Validar HTTPS, host exacto, ruta de video, autor e identificador; rechazar
   credenciales, puertos explícitos, fragmentos y fotos. Canonicalizar eliminando
   seguimiento y deduplicar por publicación. Autorías contradictorias para un mismo
   identificador provocan error.
5. Adquisición: llamar al método existente `_extract_single_video_details` con el
   autor obtenido del enlace. Este reutiliza validación de autor/ID, rehidratación,
   métricas, interacción con comentarios, observación de respuestas HTTP y fallback
   DOM. No se construyen ni reproducen solicitudes a endpoints internos.
6. Proyectar exclusivamente texto e identidad de comentario necesaria para HMAC;
   descartar nombres, usernames, avatares y enlaces de comentaristas antes de pasar
   el lote al repositorio. Reutilizar la preparación existente del texto.
7. Guardar lote, metadatos verificados y checkpoint mediante las transacciones,
   reservas y deduplicación de `research_repository`; confirmar con el trabajador
   independiente existente.

No se modificaron `reference_engine`, `reference_runtime`, `session` ni el motor
vendorizado. YouTube y la fuente sintética permanecen registrados.

## Estructuras soportadas y límites de confianza

La búsqueda admite enlaces dentro de `main` o marcadores de resultados específicos,
y `__UNIVERSAL_DATA_FOR_REHYDRATION__.__DEFAULT_SCOPE__["webapp.search"].itemList`.
Esta última es una estructura de fixture explícitamente soportada, **no una API
estable ni una estructura confirmada en TikTok real**. La ausencia de ella permite
continuar con enlaces DOM válidos. Los enlaces son candidatos con autor declarado
por URL; la autoría de la publicación se confirma posteriormente con su JSON de
video antes de almacenar comentarios. No se atribuye contenido verificado al
candidato por la sola existencia del enlace.

Si no hay candidatos y no existe el marcador vacío reconocido
`[data-e2e="search-empty"]`, se informa `source_structure_changed`: no se transforma
una estructura desconocida en un resultado vacío demostrado. Las métricas de
candidatos sin JSON permanecen ausentes; se enriquecen durante adquisición usando
la verificación del motor activo, incluso si no se recuperan comentarios.

Los resultados expresan la relevancia de búsqueda de TikTok. No hay reclasificación
semántica ni categorías/disciplinas predefinidas. No se extraen transcripciones ni
se garantiza adquisición de respuestas anidadas.

## Checkpoints locales, sin inventar cursores de TikTok

El adaptador no dispone de un cursor remoto estable verificable. Utiliza un
checkpoint **local** `v/count/digest`: número de elementos observados y SHA-256 del
prefijo de identidades, sin texto ni usernames de comentaristas. Cada lote vuelve
a abrir la interfaz y recupera un prefijo acotado para validar y continuar.

- Se necesita observar un elemento adicional para afirmar que hay otro lote local.
- Si el orden cambia, faltan elementos previamente observados o el checkpoint es
  inválido, se pausa con `checkpoint_changed`; no se salta silenciosamente al offset.
- Si un lote está guardado con confirmación pendiente, el trabajador conserva el
  comportamiento anterior: confirma sin volver a consultar la fuente.
- Una interrupción antes de guardar puede repetir navegación. No se afirma
  procesamiento exactamente una vez en la red.
- Los elementos nuevos posteriores al punto donde deja de cargar la interfaz no
  quedan garantizados. `source_complete` siempre es falso para este adaptador:
  el final observado no demuestra agotamiento de TikTok.

La repetición de prefijos consume navegador, tiempo y memoria crecientes hasta el
límite por publicación; no equivale a paginación remota eficiente. Es un recorrido
conservador para validar la integración. El crecimiento aproximado de navegación
puede ser cuadrático respecto a lotes de una misma publicación. No extrapolar las
cargas controladas al rendimiento real. En corpus cuyo orden sea inestable deberá
revisarse la estrategia con evidencia autorizada, sin evadir restricciones.

## Configuración y uso

```json
{
  "topic": "Cualquier tema libre",
  "source": "tiktok",
  "target_records": 600,
  "limits": {"batch_size": 50, "lease_seconds": 60},
  "source_config": {
    "max_publications": 50,
    "max_comments_per_publication": 200,
    "max_scrolls": 12,
    "batch_timeout_seconds": 45
  }
}
```

Rangos: 1–200 publicaciones; 1–2000 comentarios observados por publicación;
1–30 desplazamientos de búsqueda; timeout 10–50 segundos por lote. La reserva debe
superar el timeout en más de cinco segundos. Los desplazamientos de comentarios
son los del motor existente, acotados por el prefijo solicitado y el timeout total.
El objetivo conserva el máximo general configurado para investigaciones y cuenta
solo preparados válidos/únicos; 400/600/1000 o más son objetivos, no promesas.

La interfaz muestra TikTok seleccionable sin variables de habilitación;
permite configurar publicaciones, comentarios y desplazamientos. Mantiene los
contadores y controles existentes, sin presentar TikTok como fuente sintética.

Se amplía `POST /api/research/studies` con configuración TikTok y
`GET /api/research/sources` con su disponibilidad. El resto de rutas existentes
mantiene inicio, pausa, reanudación, cancelación, resultados y progreso. No hay
nuevas rutas de scraping directo ni solicitudes largas dentro de HTTP.

```bash
.venv/bin/python -m uvicorn backend.main:app --reload
.venv/bin/python -m backend.manage research-worker
```

Recomendado un trabajador local para el perfil Chromium compartido. La ocupación
de sesión produce reintentos limitados, nunca perfiles paralelos para superar una
restricción. El sistema no inicia adquisición al abrir una pestaña ni al crear un
estudio: requiere Inicio y trabajador.

## Persistencia y privacidad

Se utilizan las cuatro colecciones `research_*`, sin nuevas colecciones o índices.
Para TikTok `publication_id` es la URL canónica, que permite reconstruir y comprobar
el autor sin consultar un perfil. También se guardan `canonical_url`, `platform_id`,
`author_handle` de la **publicación**, versión del adaptador, descripción preparada
y métricas conocidas. El nombre del publicador no es identidad de comentarista.

Los comentarios analíticos conservan HMAC limitado al estudio, texto preparado,
publicación y versión. El ID original de comentario solo se utiliza en memoria
para generar HMAC. En fallback DOM sin ID se usa SHA-256 del texto como identidad
transitoria: textos idénticos dentro de una publicación se colapsan aunque procedan
de personas distintas. No se usa username para deduplicar esos registros.
Cambios de texto con el mismo ID no actualizan registros anteriores.

Se mantienen riesgos residuales de reidentificación por texto y contexto; la
preparación no es anonimización irreversible. No se promete cobertura de todos
los comentarios ni se completa el objetivo con fixtures. La persistencia real de
MongoDB fue validada en una fase anterior; esta entrega no escribe en bases reales
ni acredita por sí sola comportamiento de TikTok con MongoDB real.

## Restricciones y errores

CAPTCHA, autenticación, redirecciones inesperadas y HTTP 401/403/429 detienen el
recorrido. No se eliminan overlays, no se resuelven desafíos, no se aplica stealth,
no se copian cookies ni se reproducen llamadas protegidas. `access_restricted`,
`source_permission_missing`, `source_structure_changed` y `checkpoint_changed`
pausan el estudio conservando cursor. Reanudar no remueve ninguna restricción: el
operador debe corregir la causa; no se reinicia silenciosamente el checkpoint.
Errores transitorios de navegador y sesión usan los reintentos acotados existentes.
Pausa/cancelación se comprueban entre lotes; el timeout limita una navegación en curso.
Los mensajes públicos contienen códigos permitidos, no respuestas ni excepciones
originales. Los recursos del navegador se cierran en la salida del lote.

## Verificación

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_research_tiktok.py' -v
.venv/bin/python -B -m unittest discover -s tests
node --test tests/*.cjs
```

Fixtures: búsqueda con rehidratación, enlaces duplicados/ajenos, publicación que
aparece al desplazar, resultado vacío reconocido, estructura desconocida, 403,
CAPTCHA, autor incorrecto y comentarios HTTP repetidos/de otra publicación.
Se comprueba habilitación antes del navegador externo, URLs, checkpoints cambiados, cargas
controladas de 400/600/1000 y recuperación después del guardado, privacidad y pausa
por restricción. La prueba de interfaz selecciona TikTok sin habilitación de adquisición y muestra
la pausa de un conector controlado. Los objetos usan
`source=tiktok` y `synthetic=false` para comprobar contratos; no son datos reales.

Validación anterior del adaptador: **261 pruebas Python en 49,619 s**: 256 satisfactorias, cuatro
fallos conocidos (Big Five y SocialMind en tres anchuras) y una omisión por snapshot
externo ausente. Las ocho pruebas del nuevo módulo y la nueva prueba de interfaz
pasaron. Los cinco archivos JavaScript pasaron y `git diff --check` no detectó
errores. No se atribuyen los tiempos de fixtures a TikTok real.

Corrección de disponibilidad: se ejecutaron únicamente siete pruebas específicas,
todas satisfactorias en 8,709 s. Comprueban selección y creación sin variables,
Inicio en cola y pausa del trabajador antes del navegador externo, recolector local
simulado sin habilitación, descubrimiento interceptado, capacidades y selección de
YouTube/TikTok en la interfaz. Se verificó que el motor original, YouTube, conexión
MongoDB, repositorio y trabajador permanecieran sin cambios respecto al inicio de
esta corrección. No se repitió la suite completa ni hubo adquisición externa.

Antes de cualquier adquisición real se necesita autorización explícita para la
prueba y permiso aplicable de la fuente; después, un piloto pequeño aislado que
confirme DOM, JSON, identidad, comentarios, consumo y acceso. No se ha realizado
ese piloto y no debe considerarse esta integración validada en TikTok real.

## Observabilidad del trabajador

[Activación, archivos y lectura del diagnóstico local](tiktok-diagnostics.md).
La instrumentación no ejecuta adquisición ni modifica los controles de acceso.
