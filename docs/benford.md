# Benford — Análisis Estadístico

El panel analiza una sola métrica de publicaciones ya almacenadas. No ejecuta
Playwright, scraping ni OpenAI; no crea colecciones, índices o documentos.

## Uso

Con el entorno y MongoDB configurados como en el README, ejecutar `bash start.sh`,
abrir `http://127.0.0.1:8000` y elegir **Benford — Análisis Estadístico**.
Seleccionar perfil, métrica y conjunto, y pulsar **Analizar distribución**.
Cambiar parámetros borra el resultado anterior, pero no inicia cálculos.
**Actualizar perfiles** permite volver a consultar el selector.

## Fuentes y política de selección

- El selector reutiliza `GET /api/stored-profiles` (`profiles`).
- **Última extracción registrada**: `extraction_runs`, filtrado por
  `profile_username_key` y `status=saved`, ordenado por `extracted_at` y `run_id`
  descendentes. Se analizan exclusivamente `snapshot.publications` y sus métricas
  de esa extracción. Se devuelve su identificador y fecha. Si no existe snapshot,
  se informa sin sustituirlo por el historial. Un snapshot vacío sigue siendo una
  extracción existente con cero publicaciones.
- **Historial**: colección `publications`, que ya conserva la última observación
  de cada publicación mediante upsert. Se toma una observación por
  `publication_id`, ordenando por `last_seen_at`, `last_run_id` e `_id` descendentes
  para resolver posibles duplicados heredados de forma determinista. Se conserva
  la observación elegida incluso si su métrica falta; no se rescata un valor antiguo.
  No se suman snapshots ni observaciones temporales de una misma publicación.
  Los empates usan esos identificadores, no una cronología inferida.
- Las capturas demo de `.media-scraper/captures/` son archivos locales y no se
  mezclan con las extracciones de MongoDB.

Los registros sin un ID de publicación válido se omiten antes del cálculo y se
informan por separado. `total_records` cuenta publicaciones únicas con ID válido;
`valid_records + excluded_records = total_records`. `duplicates_removed` y
`invalid_publication_records` no se agregan a ese total.

## API

`GET /api/benford/{username}?metric=views&dataset=latest`

| Parámetro | Valores |
|---|---|
| `username` | Perfil almacenado; 1–24 letras ASCII, números, puntos o guiones bajos; `@` inicial opcional |
| `metric` | `views`, `likes`, `comments_count`, `shares`, `saves` |
| `dataset` | `latest` (predeterminado), `history` |

`metric` es la clave dentro de `publications.metrics`; comentarios usa
`comments_count`, no el campo `comments` de la respuesta del scraper.

La respuesta documentada en `/docs` contiene fuente, política, recuentos,
exclusiones por causa, nueve filas de distribución, MAD, χ², recuentos esperados,
advertencias e interpretación determinista. `status` es `exploratory` o `empty`.
Sin datos válidos devuelve 200 con medidas y frecuencias observadas `null`, no
una distribución de ceros ficticia. Perfil ausente: 404; parámetros inválidos:
422 antes de conectar a MongoDB; fallo de almacenamiento: 503 con mensaje seguro.

## Matemáticas y alcance científico

Para cada dígito d=1,…,9, se calcula `p(d)=log10(1+1/d)` mediante `math.log10`.
Se aceptan números originales finitos positivos, incluidos decimales. El primer
dígito se obtiene con `Decimal` para evitar errores logarítmicos cerca de potencias
de diez. Booleanos, cadenas (también `"123"`, `"1.2K"`), infinitos y NaN son
inválidos; nulos/ausentes, ceros y negativos tienen contadores independientes.
El módulo no puede reconstruir la precisión que se perdió antes de guardar una
métrica redondeada por el scraper o normalizador.

Con n valores válidos, `O_d` es el conteo y `E_d=n*p(d)`:

- Frecuencia observada: `O_d/n`; el gráfico presenta porcentajes.
- MAD: `sum(abs(O_d/n-p(d)))/9`, en probabilidades (escala 0–1).
- χ²: `sum((O_d-E_d)**2/E_d)`, descriptivo y sensible al tamaño de muestra.
- Diferencia de cada dígito: `100*(O_d/n-p(d))`, en puntos porcentuales.

Se comprueba el criterio conservador de que **todos** los recuentos esperados sean
al menos cinco. Con nueve categorías Benford esto requiere al menos 110 valores
válidos; diez videos no lo satisfacen. Cumplirlo no garantiza independencia,
muestreo representativo ni aplicabilidad de Benford. Por eso **nunca se calcula un
valor p** (`p_value=null`, `inference_performed=false`) ni se clasifica una cuenta
como «cumple» o «no cumple». Se declaran ocho grados de libertad nominales.

Se informa también la diferencia de exponentes decimales entre máximo y mínimo:
`orders_spanned`. Si es menor que dos se avisa de rango estrecho; es una observación
exploratoria, no una prueba de elegibilidad. Las métricas de una misma cuenta pueden
ser dependientes y la selección de videos no es aleatoria.

**Una desviación no demuestra bots, fraude, compra de seguidores ni manipulación.
Una distribución cercana tampoco demuestra autenticidad.**

Fundamentos: [definición de Benford, NIST](https://xlinux.nist.gov/dads/HTML/benfordslaw.html)
y [χ² y recuentos esperados, NIST](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/chsqgood.htm).

## Implementación y pruebas

- `backend/benford.py`: cálculo puro e interpretación.
- `backend/benford_repository.py`: selección y deduplicación de datos.
- `backend/benford_routes.py`: conexión existente, validación, errores y esquema.
- `frontend/benford.js`: selector, estados, SVG accesible, tabla e interpretación.

Sin TikTok, Atlas ni llamadas pagadas:

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_benford*.py' -v
node --test tests/test_benford.cjs
```

Las pruebas de navegador necesitan el Chromium existente de Playwright. Utilizan
rutas interceptadas y datos controlados, sin consultar servicios externos.

Verificación de esta integración: las 16 pruebas nuevas de Python y los cuatro
casos del controlador JavaScript pasan. La suite completa ejecutó 220 pruebas,
con los mismos cuatro fallos de aserción de interfaz previamente identificados
(etiquetas de Big Five y tres anchuras de SocialMind) y una omisión por ausencia
del snapshot externo de reproducción. No se modificaron esos módulos para ocultar
los fallos. La conexión a Atlas con datos reales no se verificó en esta ejecución.
