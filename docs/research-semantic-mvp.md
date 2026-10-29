# Inteligencia semántica de Investigación Temática

El análisis usa la investigación finalizada seleccionada en **Investigación Temática**.
Lee únicamente comentarios de `research_records` con su `study_id`, conserva
identificadores, texto preparado, fuente y procedencia, y guarda resultados derivados
en `research_analyses`. No ejecuta scraping ni modifica los comentarios originales.

## Uso

1. Reiniciar el backend habitual y abrir `http://127.0.0.1:8000`.
2. Entrar en **Investigación Temática** y seleccionar una investigación finalizada.
3. Revisar el nombre, la cantidad de comentarios y el estado del análisis.
4. Pulsar **Consultar análisis guardado** para leer sin llamadas a OpenAI. Si no existe,
   pulsar **Analizar N comentarios** cuando esté habilitado. La interfaz avisa del
   posible costo antes del botón. Si la petición tarda, consultar el análisis guardado
   antes de reintentar.

Los endpoints son GET y POST `/api/research/studies/{study_id}/analysis`. GET solo
lee MongoDB. POST valida el corpus completo, consulta embeddings y salida estructurada
del proveedor existente y guarda el resultado. Un hash del corpus y una identidad
determinista distinguen versiones y detectan textos, identificadores o procedencias
desactualizadas en v2. El análisis v1
guardado de cable UTP sigue consultable sin volver a generar resultados; los nuevos
análisis usan v2.

Las categorías propuestas son dudas técnicas, preguntas generales, solicitudes
comerciales, opiniones sociales y contexto insuficiente. Las preguntas y necesidades
solo usan comentarios clasificados como preguntas; los temas pueden representar
tendencias no educativas. Cada hallazgo y actividad muestra sus comentarios de
respaldo, recuentos calculados de referencias únicas y citas literales comprobadas.
La clasificación, agrupación y pertinencia pedagógica no tienen validación humana.
No se inventan enlaces, cursos ni certificaciones; las actividades quedan pendientes
de revisión educativa.

## Límites

Por defecto se analizan como máximo 100 comentarios y 50 000 caracteres preparados
por solicitud. `RESEARCH_ANALYSIS_MAX_COMMENTS` permite entre 1 y 200;
`RESEARCH_ANALYSIS_MAX_TEXT_CHARS` entre 1 y 100 000. Un corpus que exceda cualquiera
de los límites se rechaza con un mensaje explícito: no se trunca ni se presenta como
completo. La salida estructurada tiene un límite de tokens acotado; si el proveedor
la devuelve incompleta, el análisis queda fallido y no se publica un resultado parcial.
Los vectores válidos de un mismo corpus pueden reutilizarse. Una reserva `processing`
tras una muerte abrupta del servidor requiere revisión del operador.

La agrupación usa similitud coseno y enlace completo con umbral exploratorio 0,58;
no está calibrado. Los casos sin vecinos suficientes permanecen individuales.

## Verificaciones realizadas

- Consulta real de MongoDB: cable UTP, 37 comentarios, análisis v1 `completed`;
  inteligencia artificial, 75 comentarios, `unavailable` y elegible. Los hashes de
  ambos corpus originales coincidieron antes y después de la consulta.
- La interfaz real en Chromium leyó el análisis UTP, mostró habilitado **Analizar 75
  comentarios** para inteligencia artificial y limpió el resultado anterior al
  cambiar. No envió ningún POST.
- Pruebas controladas con proveedor simulado cubren persistencia por `study_id`,
  37/75 comentarios, cambio de estudio, corpus vacío, límites, hash desactualizado,
  citas y errores. Esas pruebas no acreditan una ejecución real de OpenAI para los
  75 comentarios. Esa ejecución queda para el operador desde la interfaz.
