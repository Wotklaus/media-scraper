# Big Five: corrección y verificación

## Diagnóstico y límites de la evidencia

Los dos botones comparten `SemanticAnalysis.generate` y `request_structured`.
Antes de los cambios se inspeccionaron prompt, publicaciones, esquema Pydantic,
Responses, parsing, validación de citas, reserva en MongoDB y rutas HTTP.

Defectos reproducibles del flujo anterior:

- `publication_id` y `publication_ids` eran cadenas libres en el esquema enviado.
  Los IDs desconocidos solo se detectaban después de recibir una respuesta pagada.
  No había validación de unicidad/tipo de los IDs de entrada antes de reservar el intento.
- La comparación literal rechazaba diferencias de espacios, saltos de línea y composición
  Unicode, incluso cuando el fragmento conservaba las mismas palabras y puntuación.
- Interpretación: cualquier tema, observación o resumen con una cita inválida descartaba
  el informe entero. La validación estructural global también impedía recuperar hallazgos
  independientes cuando otro hallazgo incumplía sus límites.
- OCEAN: cualquier indicador inválido descartaba las otras dimensiones. El parsing global
  también impedía recuperar dimensiones omitidas o indicadores estructuralmente inválidos.
- Los diagnósticos agrupaban errores estructurales y de evidencia, sin identificar
  referencias desconocidas, citas ausentes o cobertura incompleta.

No se dispone en esta revisión del payload ni de la referencia técnica de los intentos
históricos observados en Brave. Por tanto, no se puede confirmar qué defecto produjo
cada fallo concreto. Tampoco se ha probado una pérdida de precisión de IDs en esos
intentos: las referencias cortas eliminan esa fuente de errores de copia, pero no la
convierten en una causa histórica demostrada.

La documentación oficial confirma que `gpt-5.4-mini-2026-03-17` admite Structured Outputs
con `reasoning.effort=none`; las restricciones de longitud usadas son compatibles con
este modelo base. No se encontró evidencia de una incompatibilidad que justifique
cambiar de modelo o eliminar las restricciones:

- https://developers.openai.com/api/docs/models/gpt-5.4-mini
- https://developers.openai.com/api/docs/guides/structured-outputs

El flujo previo ya distinguía respuestas truncadas y rechazos antes de validar JSON.
Se conservó ese comportamiento: no se recupera JSON truncado ni se reintenta de forma automática.

## Corrección

1. Validar IDs únicos de texto antes de crear cliente/reservar intento.
2. Enviar `p1`…`p10` con sus textos; restringir las referencias mediante `enum` en
   ambos campos del JSON Schema. Restaurar IDs originales mediante un mapa exacto
   antes de validar y persistir. Nunca adivinar una referencia desconocida.
3. Comprobar estado/rechazo antes del parsing. Separar JSON ilegible, estructura,
   referencias, cobertura de evidencias y citas.
4. Validar cada hallazgo/indicador completo. Si una de sus referencias o citas falla,
   se descarta el hallazgo entero, sin conservar una afirmación con respaldo reducido.
   Los demás hallazgos verificables permanecen. Resumen descartado: `summary=null`.
5. Normalizar solo espacios y composición Unicode NFC para cotejar citas; sin similitud
   difusa, traducción ni corrección de palabras o puntuación.
6. Marcar los resultados recuperados como parciales. Dimensiones faltantes de OCEAN:
   evidencia insuficiente. Índices calculados por el servidor a partir de publicaciones
   únicas verificadas, con mínimo de dos respaldos; nunca puntuaciones psicológicas.
7. Si todas las evidencias propuestas son inválidas, guardar el intento fallido, no un
   análisis válido. OCEAN puede informar explícitamente ausencia de indicadores sin
   inventar resultados positivos.
8. Conservar diagnósticos con categorías y rutas del esquema, sin prompts, citas,
   cuerpos de errores del proveedor o credenciales.

Las versiones de prompt pasan a v2 para separar este contrato del anterior; los registros
anteriores permanecen intactos. Los resultados v2 vigentes, incluidos los parciales,
se reutilizan. Un cambio de contenido/modelo/prompt requiere acción manual para generar
un resultado nuevo; la lectura nunca lo genera.

No se modificaron el cálculo PCA, embeddings, scraper, extracción, configuración de
Playwright, General ni Estadísticas. Se conservaron los cambios locales preexistentes.
No hubo llamadas pagadas, conexión a Atlas, borrado de registros, commits ni pushes.

## Dashboard

Selector y tres indicadores arriba; mapa y embeddings en la segunda fila; relaciones e
interpretación en la tercera; cinco dimensiones OCEAN en la cuarta. Se eliminó por completo
el recuadro Temáticas principales. La API conserva temas respaldados para no romper su
contrato, pero ese recuadro ya no existe en el dashboard.

El mapa usa escala uniforme sobre las coordenadas PCA originales, sin jitter ni layout
que las altere. Dibuja solo pares calculados presentes en el top 5 y con coseno ≥ 0.50.
El umbral es de visualización, no una afirmación de significación estadística. El tamaño
representa el número de conexiones dibujadas. La selección resalta también los pares
relacionados y ofrece detalles/enlaces laterales. Las etiquetas que no caben sin colisión
se omiten; la botonera permite seleccionar incluso puntos coincidentes.

## Pruebas ejecutadas

- 82 pruebas Python: `test_semantics`, `test_ocean`, `test_analysis_recovery`,
  `test_embeddings`, `test_stored_profiles`. Incluyen transporte real del SDK con
  MockTransport local, parsing, esquema con enums, IDs largos, recuperación parcial,
  rechazo sin respaldo, HTTP, persistencia simulada, reutilización y aislamiento.
- 38 pruebas JavaScript: `tests/test_big_five.cjs` (12) y
  `tests/test_semantic_dashboard.cjs` (26). Incluyen botones independientes, ausencia
  de POST al seleccionar, recargar/selección fuera de orden, enlaces, interacción,
  conexiones calculadas y presentación parcial.
- Brave headless, perfil temporal, todas las rutas interceptadas: 1440/1024/390 px,
  10 puntos, 5 conexiones, selección lateral, ambos análisis simulados y recarga con
  resultados almacenados simulados. Sin errores de página ni overflow horizontal.
- Sintaxis de JavaScript y `git diff --check`.

El sandbox bloqueó el arranque de Brave y la ejecución de las pruebas HTTP en hilos;
estas comprobaciones se completaron fuera del sandbox con aprobación. No se alteró el
navegador del usuario. Las pruebas no acreditan funcionamiento real del proveedor ni
persistencia nueva en Atlas.

## Verificación manual en Brave

1. Reiniciar el backend con `./start.sh` y abrir `http://127.0.0.1:8000`.
   Recargar los recursos con Ctrl+Shift+R. En DevTools → Network, filtrar `/api/`.
2. Abrir Big Five y seleccionar un perfil almacenado. Solo debe haber GET al consultar
   publicaciones, mapa y resultados. Cambiar de perfil y recargar tampoco deben generar POST.
3. Embeddings: si ya están vigentes, el botón debe permanecer deshabilitado y el mapa
   debe usar los vectores existentes. No regenerarlos para comprobar el rediseño.
   Si hay pendientes y se desea autorizar su costo, pulsar Generar embeddings una sola vez:
   debe enviarse solo POST `/api/embeddings/{perfil}?limit=10`.
4. Contenido: pulsar Analizar contenido con OpenAI una sola vez si no existe un análisis
   vigente. Debe enviarse solo POST `/api/semantics/{perfil}/analysis`. Revisar resumen,
   enlaces de respaldo y aviso parcial cuando proceda. El botón debe deshabilitarse al
   obtener un resultado vigente. Si falla, conservar el código y la referencia de la
   respuesta HTTP; buscar `analysis_failure`/`analysis_discard` en la consola del servidor.
5. Big Five: pulsar Analizar Big Five una sola vez si no existe un resultado vigente.
   Debe enviarse solo POST `/api/semantics/{perfil}/ocean`. Revisar las cinco dimensiones,
   indicadores, citas/enlaces, cobertura e insuficiencia de evidencia. No deben aparecer
   mediciones de personalidad. Evitar Regenerar análisis salvo que se quiera otra llamada pagada.
6. Recargar y volver al mismo perfil: deben reaparecer los resultados desde GET, sin POST.
7. Mapa: probar hover, clic, Tab/Enter, selección por números y relaciones en el lateral.
   Reducir la ventana: no debe haber scroll horizontal. Puntos coincidentes se seleccionan
   con la botonera; no se desplazan artificialmente.

Los pasos que pulsan botones sin resultados vigentes implican solicitudes reales pagadas.
No se ejecutaron durante esta revisión. Para atribuir un fallo histórico concreto faltan
sus diagnósticos; no es necesario repetir llamadas pagadas para informar esa limitación.

## Archivos cambiados en esta corrección

- `backend/structured_analysis.py`
- `backend/semantic_analysis.py`
- `backend/ocean_analysis.py`
- `backend/analysis_errors.py`
- `frontend/big-five.js`
- `frontend/index.html` (solo Big Five)
- `frontend/style.css` (reglas limitadas a Big Five)
- `tests/test_semantics.py`
- `tests/test_semantic_dashboard.cjs`
- `tests/test_analysis_recovery.py` (nuevo)
- `docs/big-five-verification.md` (nuevo)
