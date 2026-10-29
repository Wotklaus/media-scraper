# MVP de inteligencia semántica de Investigación Temática

El MVP usa exclusivamente la investigación `233a3985-c2d3-4f1e-b67a-b5c0e37a1659`
(`cable utp`) y sus 37 comentarios preparados de TikTok. Requiere investigación
finalizada, claves únicas, textos no vacíos y procedencia no sintética. Rechaza
otro study_id, un corpus incompleto o una adquisición aún activa. No ejecuta scraping.

## Uso

1. Iniciar/reiniciar el backend habitual con el código actualizado y abrir
   `http://127.0.0.1:8000`.
2. Entrar en **Investigación Temática** y seleccionar **cable utp**, identificador
   corto **233a3985**. Usar Siguientes/Anteriores si no está en la primera página.
3. En **Inteligencia semántica · MVP**, consultar el análisis guardado o pulsar
   **Analizar 37 comentarios**. El botón informa que envía textos preparados a OpenAI
   y puede generar costo. No se ejecuta análisis por seleccionar la investigación.
4. Revisar categorías, ambigüedades, grupos, necesidades/FAQ/temas y actividades.
   Cada apartado permite desplegar comentarios originales preparados y citas.

La generación usa la configuración local existente de OpenAI en `backend/.env`.
No se exponen credenciales en la interfaz. GET no crea el cliente ni genera vectores.
Un resultado vigente se reutiliza; el botón no vuelve a generar un análisis completado.
Ante fallo se puede reintentar expresamente. Los embeddings válidos del mismo hash
se conservan y reutilizan. Si la petición del navegador vence, consultar primero el
análisis guardado: el servidor puede seguir trabajando. Un estado processing no
dispara otra generación. Tras una muerte abrupta del servidor, una reserva processing
requiere revisión del operador; no se roba automáticamente para evitar cargos duplicados.

## Recorrido integrado

`research_routes` → `ResearchAnalysis.source()` (solo lectura de research_records)
→ embeddings en un lote de 37 con el cliente/modelo existentes de `embeddings.py`
→ similitud coseno y agrupación complete-link determinista → salida estructurada
con `request_structured()` → validación de referencias/citas → `research_analyses`.

Los endpoints son GET y POST `/api/research/studies/{study_id}/analysis`. Solo POST
genera resultados. La sección muestra estados unavailable, stale, processing, failed
y completed. Los errores del proveedor se presentan mediante los diagnósticos
saneados existentes; no se sustituyen por resultados inventados.

Cada comentario conserva en el resultado su record_key, _id, publication_id, texto
preparado, categoría, cita literal, razón y alternativas/ambigüedad. El proveedor solo
recibe referencias cortas y textos, sin los URLs de las publicaciones ni credenciales.
La clasificación es automática y no se presenta como referencia validada por humanos.

Los grupos usan coseno con umbral exploratorio 0,58 y enlace completo: todos los pares
de un grupo cumplen el umbral. No se afirma que esté calibrado. Los comentarios que
no se unen quedan como grupos individuales; no se inventa pertenencia. No se usa la
PCA existente limitada a diez publicaciones ni se instala una biblioteca adicional.
El umbral inicial 0,72 produjo 37 grupos individuales sobre los vectores reales;
se ajustó a 0,58 tras inspeccionar su distribución, sin afirmar calidad validada.

Los hallazgos tienen cantidades calculadas desde IDs únicos, no cifras del modelo.
Las necesidades y FAQ solo pueden citar dudas técnicas; una FAQ requiere al menos dos
comentarios. Una clasificación o un título semántico no queda validado por el mero
hecho de que una cita sea literal: todos requieren revisión de contenido.

Las recomendaciones son actividades propuestas, respaldadas por dudas técnicas de
los hallazgos. No hay catálogo externo validado: **ninguna actividad se marca como
verificada pedagógicamente**. Se verifican solo las citas de respaldo. No se inventan
enlaces, cursos ni certificaciones; se rechazan referencias o recursos ajenos al MVP.

## Persistencia y límites

`research_analyses` guarda un documento derivado por study_id + hash del corpus +
modelos + versión + umbral. El _id determinista evita generaciones concurrentes del
mismo análisis. Se conservan vectores, modelos, fecha, agrupación, resultado o fallo.
Las rutas públicas no devuelven los vectores. Se comprueba de nuevo el hash antes
del commit para evitar publicar un análisis de una captura modificada.

No se actualizan research_records, research_publications, tareas ni contadores del
scraper. No se modifican V1/V2, su adquisición ni la infraestructura de MongoDB.
Una petición fallida de clasificación no publica hallazgos parciales como completados.

## Comprobaciones específicas

```bash
PYTHONPATH=tests .venv/bin/python -B -m unittest test_research_analysis
PYTHONPATH=tests .venv/bin/python -B -m unittest test_research_analysis_browser
node --test tests/test_research.cjs tests/test_research_diagnostics.cjs
```

Las pruebas controladas verifican aislamiento del estudio, integridad de originales,
clasificación/citas, caché, agrupación sin encadenamiento transitivo, fallo y reintento,
rechazo de recursos inventados, presentación y estados de UI. Sus respuestas de
proveedor son fixtures de regresión, nunca un fallback del producto. La comprobación
con el proveedor y los documentos reales debe distinguirse de esas pruebas; no se
presentan los fixtures como análisis de los 37 comentarios reales.

## Verificación sobre los comentarios reales

El 29 de octubre de 2026 se ejecutó el análisis bajo demanda sobre los 37 documentos
de esta investigación. El resultado vigente quedó en `research_analyses`: 14 dudas
técnicas, 13 solicitudes comerciales, 7 opiniones sociales y 3 comentarios con
contexto insuficiente. Los vectores reales forman 30 grupos (7 pares y 23 casos
individuales). Se publicaron 4 hallazgos respaldados y 2 actividades propuestas;
1 hallazgo y 3 actividades sin respaldo suficiente quedaron omitidos y se muestran
como avisos.
La API GET y la interfaz en Chromium leyeron el resultado guardado sin POST ni
scraping. Un hash de los 37 documentos originales antes y después coincidió.

Esta verificación confirma la ejecución y persistencia del análisis, no la calidad
humana de las etiquetas, el umbral ni la eficacia de las actividades. Las actividades
no tienen fuentes externas o cursos verificados y siguen pendientes de revisión
educativa.
