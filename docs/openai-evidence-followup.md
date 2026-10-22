# OpenAI: investigación de referencias y alineación del menú

## Evidencia histórica comprobada

Se consultó MongoDB exclusivamente mediante lecturas. No hubo llamadas a OpenAI.

| Análisis | Referencia encontrada | Perfil del registro | Estado / etapa |
| --- | --- | --- | --- |
| Interpretación | `859fa8e4-2db2-4406-a81c-7c9cceaa14ee` | `zonaatrading` | failed / validation |
| OCEAN | `2a201800-d786-48f6-883a-67375d2ae5f2` | `zonaatrading` | failed / validation |

Ambos registros tienen `failure.code=evidence_missing`; las versiones de prompt son
`observable-content-v2` y `ocean-linguistic-signals-v2`. Sus inicios son respectivamente
2026-10-22 15:58:01.174 y 15:58:20.623 (fechas UTC guardadas por el servidor).

**El nombre almacenado es @zonaatrading, con dos letras a.** La consulta por @zonatrading
no encontró el perfil. No se renombró ni alteró ningún registro.

No se encontraron logs locales con estas referencias. Los documentos de fallo no contienen
respuesta del proveedor, desglose de hallazgos ni motivos individuales de descarte.
Por ello no se puede establecer el número histórico recibido/aceptado/rechazado ni afirmar
que las citas alteradas hayan sido la causa de esos dos intentos concretos.

En el código v2 inspeccionado:

- `validate_interpretation(..., recover=True)` lanza `evidence_missing` cuando no queda
  ningún resumen/tema/observación válido. Antes no distinguía una respuesta explícitamente
  vacía de una respuesta con todos los hallazgos rechazados.
- `OceanAnalysis.validate(..., recover=True)` lanza ese código si hubo indicadores
  rechazados y no se conservó ninguno. Una respuesta de cinco dimensiones con indicadores
  vacíos ya se trataba como evidencia insuficiente. Según ese flujo, el fallo OCEAN no
  equivale simplemente a que el modelo devolviera cero indicadores.
- `validate_finding` exige IDs conocidos/únicos, igualdad entre IDs de respaldo e IDs de
  las evidencias y citas presentes en el texto de cada publicación, tras NFC y normalización
  de espacios. Citas inventadas, corregidas, resumidas o con puntos suspensivos añadidos
  no cumplen esa última condición.

## Datos de entrada y mapeo

La lectura de las fuentes de @zonaatrading devolvió diez descripciones no vacías: 2988
caracteres almacenados, 2980 después de quitar espacios externos. El límite es 24000.
El envío usa descripciones completas, no los extractos abreviados del mapa. La única
transformación de entrada es `.strip()`; no hay truncamiento de las descripciones.

| Referencia enviada | ID original esperado al validar | Longitud enviada |
| --- | --- | ---: |
| p1 | 7698141302722006293 | 464 |
| p2 | 7697711191287745813 | 437 |
| p3 | 7697367323493158165 | 472 |
| p4 | 7697133166242336020 | 152 |
| p5 | 7696658094880853269 | 438 |
| p6 | 7695210286684441877 | 220 |
| p7 | 7693631824571976980 | 128 |
| p8 | 7693184881643277588 | 93 |
| p9 | 7692871283029167380 | 336 |
| p10 | 7691795751713721620 | 240 |

El mapa de referencias y el prompt se construyen a partir de la misma lista en el mismo
orden dentro de `SemanticAnalysis.generate`. `restore` sustituye exactamente los aliases
antes de validar. Las pruebas con esta copia de las fuentes confirman que un alias válido
vuelve al ID original. **No se reprodujo un error de mapeo de IDs.** Los originales permanecen
como cadenas; no pasan por conversiones numéricas de JavaScript.

## Reproducción y cambio concreto

La reproducción utiliza las descripciones leídas de MongoDB y respuestas simuladas.
No intenta presentarlas como respuestas históricas recuperadas.

| Respuesta representativa | Recibidos | Aceptados | Rechazados | Resultado |
| --- | ---: | ---: | ---: | --- |
| p1 y fragmento literal real | 1 | 1 | 0 | Resultado verificable |
| p1 y fragmento con `...` añadido | 1 | 0 | 1 | `evidence_quote`, luego `evidence_missing` |
| Hallazgo literal y otro con referencia inexistente | 2 | 1 | 1 | Parcial; `evidence_reference` |
| Resumen null, temas y estilo vacíos | 0 | 0 | 0 | Ausencia explícita de evidencias |

La incompatibilidad reproducida es que el esquema anterior restringía el identificador,
pero permitía generar libremente `quote`; una cita JSON válida podía ser incompatible
con el texto original. Cambiar solo el mensaje o relajar la comparación no corrige eso.

Ahora `literal_fragments` obtiene fragmentos de hasta 79 caracteres, como slices literales
del texto almacenado. No añade puntos suspensivos ni cambia palabras. Se envían junto con
la descripción completa en `evidence_quotes`.

`source_schema` construye `Evidence` mediante `anyOf`: cada alternativa fija una sola
`publication_id` y un `enum` de citas tomadas exclusivamente de esa publicación. El modelo
elige la evidencia entre fragmentos verificables, en lugar de tener que reconstruirla.
Se mantiene la validación backend completa y la recuperación por hallazgo completo.
La composición usa las capacidades documentadas de Structured Outputs:
https://developers.openai.com/api/docs/guides/structured-outputs

No se cambió el modelo. Tampoco se invalidaron los análisis vigentes anteriores: el
contrato de validación de hallazgos respaldados sigue siendo el mismo; el cambio restringe
la generación de evidencias. No se modificaron resultados existentes.

Una interpretación explícitamente vacía se guarda como `evidence_status=insufficient_evidence`,
sin hallazgos ni puntuaciones, y se muestra como tal. Si el modelo propuso evidencias y
se rechazaron todas, el intento continúa fallando: no se convierte en un resultado válido.

## Instrumentación segura de la siguiente solicitud autorizada

Por intento se registran y preparan para persistencia futura:

- Cantidad de hallazgos/indicadores recibidos, aceptados y rechazados.
- Motivos: esquema, referencia inexistente/repetida, cobertura de citas, texto vacío o cita ausente.
- Sección de cada hallazgo y su resultado; para errores estructurales, tipo y ruta del esquema.
- Para citas rechazadas, longitud y coincidencia en la fuente esperada/otra fuente, sin la cita.
- Referencias reconocidas/no reconocidas, alias enviados, longitudes y cantidad de fragmentos.
- Identificador del intento; en fallos, también la referencia pública que ve el usuario.

Los logs no incluyen prompts, descripciones, citas, claves, cuerpos del proveedor ni valores
de errores Pydantic. Los contadores de la próxima ejecución se guardarán en el análisis
completado o en el diagnóstico de fallo. Durante esta revisión solo se escribió en dobles
de MongoDB en memoria; los registros reales históricos permanecieron intactos.

Esta instrumentación permite saber por qué se rechaza una evidencia, sin requerir guardar
respuestas completas que puedan contener datos sensibles. No hubo nueva solicitud real.

## Menú

El nuevo contenedor compartido `.content-width` se usa en `main` y en `.nav-content`.
Ambos comparten `width: min(1200px, 92%)` y márgenes automáticos. El fondo y la caja exterior
de `.main-nav` permanecen a ancho completo. Se conservan colores, tipografía y estilos de
botones. En móvil se permite envolver los botones si el espacio disponible lo requiere.

Brave headless, con perfil temporal y todas las rutas interceptadas, comprobó igualdad de
posición izquierda y ancho del contenedor en las tres secciones a 1920/1440/1024/390 px.
También verificó que la barra sigue midiendo todo el viewport. No hubo cambios del mapa,
PCA, embeddings, scraper ni configuración de Playwright. La herramienta de navegador solo
se utilizó desde un script temporal para comprobar la interfaz.

## Pruebas y límites

- 103 pruebas Python: semántica, OCEAN, recuperación parcial, fuentes/citas, embeddings,
  perfiles e integración HTTP. Incluyen las fuentes almacenadas exportadas a una copia
  temporal y transporte real del SDK con MockTransport local.
- 39 pruebas JavaScript: control de acciones y dashboard; sin cambios del mapa aprobado.
- 12 verificaciones geométricas del menú en Brave: tres secciones por cuatro tamaños.
- Sintaxis JavaScript y `git diff --check`.

La clase `StoredSourceReproduction` usa `/tmp/zonatrading-sources.json`, una copia temporal
obtenida mediante lectura. En entornos sin esa copia, esos casos se omiten expresamente;
los casos sintéticos siguen disponibles. Las fuentes no se añadieron al repositorio.

Comandos de pruebas:

```
PYTHONPATH=tests .venv/bin/python -m unittest test_semantics test_ocean test_analysis_recovery test_source_evidence test_embeddings test_stored_profiles -q
node tests/test_big_five.cjs
node tests/test_semantic_dashboard.cjs
```

**No se afirma que los dos fallos históricos estén resueltos en producción.** Se verificó
el mapeo, se reprodujo un rechazo real del validador con fuentes almacenadas, se corrigió
el contrato que permitía citas incompatibles y se añadió el diagnóstico que faltaba.
Falta comprobar la aceptación del esquema y el resultado de ambos análisis con OpenAI real;
solo se hará con autorización explícita del usuario.

## Archivos de esta intervención

- `backend/structured_analysis.py`: fragmentos literales y esquema vinculado a cada fuente.
- `backend/semantic_analysis.py`: generación, diagnósticos y ausencia explícita de hallazgos.
- `backend/ocean_analysis.py`: instrucciones y contadores de validación compartidos.
- `backend/analysis_errors.py`: extracción segura de rutas/tipos de errores.
- `frontend/big-five.js`: estado explícito de evidencia insuficiente en interpretación.
- `frontend/index.html`: contenedor interior del menú y clase compartida de main.
- `frontend/style.css`: alineación y contenedor compartido; sin cambios visuales del dashboard.
- `tests/test_semantics.py`, `tests/test_analysis_recovery.py`: expectativas del nuevo esquema.
- `tests/test_semantic_dashboard.cjs`: presentación de ausencia explícita de evidencias.
- `tests/test_source_evidence.py`: casos nuevos y reproducción con copia de fuentes almacenadas.
- `docs/openai-evidence-followup.md`: este informe.

Se preservaron los cambios locales existentes. No hubo commits, pushes, escrituras ni
borrados en MongoDB, ni regeneración de embeddings.
