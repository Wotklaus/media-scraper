<div align="center">

# 🧠 Media Scraper

**Investigación Temática (fase 1):** [núcleo, trabajador local y API](docs/research.md)
para adquirir registros controlados por lotes. **Datos de prueba — No reales**;
sin scraping temático ni consumo de OpenAI.

**Nuevo módulo:** [Benford — Análisis Estadístico](docs/benford.md), análisis
exploratorio de métricas almacenadas, sin nuevas extracciones ni consumo de IA.

### Social Media Analytics · TikTok Intelligence & Semantic Analytics

**Plataforma web para extracción, normalización, persistencia, análisis estadístico y exploración semántica de publicaciones públicas de TikTok.**

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.146.0-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.64.0-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/python/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/atlas)
[![OpenAI](https://img.shields.io/badge/OpenAI-Embeddings%20%2B%20Responses-412991?logo=openai&logoColor=white)](https://platform.openai.com/docs)
[![JavaScript](https://img.shields.io/badge/JavaScript-Vanilla-F7DF1E?logo=javascript&logoColor=black)](https://developer.mozilla.org/es/docs/Web/JavaScript)

**Proyecto académico · Ingeniería en Sistemas de Información**

**Código fuente:** [Wotklaus/media-scraper](https://github.com/Wotklaus/media-scraper) · **Rama documentada:** [`feature/setup-inicial`](https://github.com/Wotklaus/media-scraper/tree/feature/setup-inicial)

[Inicio rápido](#-inicio-rápido) · [Arquitectura](#-arquitectura-del-sistema) · [MongoDB](#-persistencia-en-mongodb-atlas) · [Embeddings](#-embeddings-de-las-publicaciones) · [PCA](#-mapa-semántico-pca) · [Coseno](#-similitud-coseno) · [Big Five](#-big-five-ocean-y-señales-lingüísticas) · [API](#-api-rest-documentada) · [Defensa](#-guía-para-la-defensa-técnica)

</div>

---

## 📑 Contenido

1. [Presentación del proyecto](#-presentación-del-proyecto)
2. [Funciones implementadas](#-funcionalidades-implementadas)
3. [Arquitectura](#-arquitectura-del-sistema)
4. [Tecnologías y librerías](#-tecnologías-y-librerías)
5. [Estructura de carpetas](#-estructura-del-repositorio)
6. [Inicio rápido](#-inicio-rápido)
7. [Scraping de TikTok](#-extracción-de-datos-de-tiktok)
8. [Normalización y mapeo](#-normalización-y-mapeo-de-datos)
9. [MongoDB Atlas](#-persistencia-en-mongodb-atlas)
10. [Embeddings](#-embeddings-de-las-publicaciones)
11. [PCA y mapa semántico](#-mapa-semántico-pca)
12. [Similitud coseno](#-similitud-coseno)
13. [Interpretación con OpenAI](#-interpretación-de-contenido-con-openai)
14. [Big Five / OCEAN](#-big-five-ocean-y-señales-lingüísticas)
15. [Interfaz](#-frontend-y-visualización)
16. [API REST](#-api-rest-documentada)
17. [Consumo y caché](#-control-de-consumo-y-reutilización)
18. [Validaciones y seguridad](#-validación-trazabilidad-y-seguridad)
19. [Pruebas y errores](#-pruebas-y-diagnóstico)
20. [Defensa](#-guía-para-la-defensa-técnica)
21. [Limitaciones](#-limitaciones-conocidas-y-alcance)
22. [Bibliografía y glosario](#-bibliografía-y-glosario)

---

## 🎯 Presentación del proyecto

**Media Scraper** es un sistema de información que integra distintos procesos sobre una misma fuente de datos públicos:

- **Adquisición:** consulta un perfil de TikTok mediante su nombre de usuario utilizando Playwright y Chromium.
- **Transformación:** normaliza métricas, publicaciones, comentarios recuperados y metadatos.
- **Persistencia:** registra información en MongoDB Atlas y conserva el historial de extracciones.
- **Visualización:** muestra un panel general, rankings de publicaciones, indicadores de interacción y hashtags.
- **Representación vectorial:** crea embeddings de las descripciones mediante OpenAI, de forma explícita y bajo demanda.
- **Análisis semántico:** calcula similitud coseno y una proyección PCA para visualizar relaciones entre publicaciones.
- **Interpretación lingüística:** analiza los textos con un modelo generativo, exige evidencias literales y almacena resultados reutilizables.
- **OCEAN / Big Five:** organiza señales lingüísticas del contenido en cinco categorías interpretativas, con referencias verificables a las publicaciones.

### Objetivo general

Desarrollar una aplicación web que permita **extraer, estructurar, almacenar y analizar información pública de perfiles de TikTok**, integrando una base de datos documental y técnicas de representación semántica e inteligencia artificial para apoyar su exploración visual.

### Objetivos específicos

1. Extraer los datos públicos disponibles de un perfil mediante su `username`.
2. Normalizar campos y preservar la diferencia entre dato ausente y valor cero.
3. Persistir perfiles, publicaciones y comentarios recuperados sin crear duplicados innecesarios.
4. Mostrar indicadores descriptivos y rankings de publicaciones.
5. Generar y reutilizar embeddings asociados a un perfil y a una versión del contenido.
6. Calcular similitudes semánticas reales y representarlas en un mapa bidimensional.
7. Interpretar contenido mediante OpenAI, con referencias y citas que puedan validarse.
8. Presentar las cinco dimensiones OCEAN como **categorías de señales observables del lenguaje**, sin confundirlas con una medición psicométrica.

### Enfoque metodológico

El sistema separa **hechos observados**, **cálculos matemáticos** e **interpretaciones generativas**. Esto permite explicar de dónde procede cada resultado y reconocer qué no puede concluirse a partir de una muestra pequeña de publicaciones.

## ✨ Funcionalidades implementadas

| Módulo | Qué permite hacer | ¿Se consulta TikTok? | ¿Puede consumir OpenAI API? |
|---|---|:---:|:---:|
| **General** | Buscar perfiles y visualizar métricas y publicaciones | Sí, al analizar | No |
| **Estadísticas** | Ordenar videos, analizar interacciones y hashtags | No, reutiliza la consulta | No |
| **MongoDB Atlas** | Guardar perfiles, videos, comentarios e historial | No adicional | No |
| **Selector Big Five** | Elegir cualquier perfil previamente almacenado | No | No |
| **Embeddings** | Generar vectores de publicaciones pendientes | No | **Sí, bajo demanda** |
| **Mapa PCA** | Ubicar vectores vigentes en dos dimensiones | No | No |
| **Similitud coseno** | Comparar publicaciones y mostrar los cinco pares más cercanos | No | No |
| **Interpretación** | Detectar temas y patrones textuales fundamentados | No | **Sí, bajo demanda** |
| **Big Five/OCEAN** | Identificar señales lingüísticas en cinco dimensiones | No | **Sí, bajo demanda** |
| **Resultados guardados** | Leer interpretaciones o señales OCEAN vigentes | No | No |
| **Exportaciones** | Descargar JSON o CSV de la consulta del perfil | No | No |

> **Regla de diseño:** cambiar de pestaña, elegir un perfil o recargar **no** ejecuta operaciones pagadas. La aplicación utiliza `GET` para consultar datos almacenados; los análisis se generan con un `POST` explícito.

## 🏗️ Arquitectura del sistema

### Arquitectura cliente-servidor y separación de responsabilidades

```mermaid
flowchart TD
  U["Usuario · Brave / navegador"] --> FE["Frontend · HTML, CSS, JavaScript"]
  FE -->|"HTTP / JSON"| API["API REST · FastAPI + Uvicorn"]
  API -->|"Consulta real explícita"| SCR["Scraper · Playwright + Chromium"]
  SCR -->|"Contenido accesible"| TK["TikTok"]
  SCR --> NORM["Normalización de datos"]
  NORM --> REPO["Repositorio transaccional"]
  REPO --> DB[("MongoDB Atlas\nmedia_scraper")]
  API -->|"POST /embeddings"| EMB["Servicio de embeddings"]
  EMB <-->|"Consultar / almacenar vectores"| DB
  EMB -->|"Texto de publicación"| OA["OpenAI API"]
  API -->|"GET /semantics/.../map"| MATH["PCA + similitud coseno"]
  MATH -->|"Leer vectores actuales"| DB
  API -->|"POST /analysis y /ocean"| NLP["Análisis generativo y verificación de citas"]
  NLP -->|"Consultar / persistir resultados"| DB
  NLP -->|"Descripciones + referencias cortas"| OA
  MATH --> FE
  NLP --> FE
```

**Decisiones de diseño:**

- El navegador **no** accede directamente a MongoDB ni conoce las claves de OpenAI.
- La API es la frontera entre interfaz, extracción, persistencia y análisis.
- Los resultados almacenados pueden consultarse **sin ejecutar Playwright**.
- Los servicios semánticos son independientes del scraper y no alteran sus datos originales.
- Se utilizan IDs estables para vincular cada vector, cita y análisis con la publicación que lo originó.

### Flujo de extremo a extremo

```mermaid
sequenceDiagram
    actor Usuario
    participant Web as Frontend
    participant API as FastAPI
    participant Tik as Playwright/TikTok
    participant Mongo as MongoDB Atlas
    participant AI as OpenAI API
    Usuario->>Web: Ingresa username y pulsa Analizar
    Web->>API: GET /api/profile/{username}?mode=real
    API->>Tik: scrape_profile(username)
    Tik-->>API: Perfil, videos, métricas y avisos
    API->>Mongo: Normalización + upsert + extraction_run
    API-->>Web: JSON del perfil
    Usuario->>Web: Abre Big Five y selecciona perfil
    Web->>API: GET perfiles, publicaciones, embeddings, mapa
    API->>Mongo: Consultas de lectura
    Mongo-->>Web: Resultados por perfil
    opt Usuario pulsa Generar embeddings
        Web->>API: POST /api/embeddings/{username}
        API->>Mongo: Buscar vectores vigentes
        API->>AI: Generar solo los vectores faltantes
        API->>Mongo: Guardar vectores nuevos
    end
    opt Usuario pulsa Analizar contenido / Big Five
        Web->>API: POST /api/semantics/{username}/analysis o /ocean
        API->>Mongo: Verificar si ya existe análisis vigente
        API->>AI: Analizar descripciones con salida estructurada
        API->>API: Validar referencias y citas
        API->>Mongo: Guardar análisis verificado
    end
    Web->>API: GET análisis guardado
    API-->>Web: Resultado reutilizable
```

## 🧰 Tecnologías y librerías

Las versiones siguientes corresponden al **`requirements.txt` de `feature/setup-inicial` comprobado en GitHub**.

### Dependencias principales

| Tecnología | Versión del proyecto | Responsabilidad |
|---|---:|---|
| **Python** | Entorno de desarrollo 3.12 | Orquestación de los módulos backend |
| **FastAPI** | `0.146.0` | API REST, enrutamiento, validaciones y respuestas HTTP |
| **Uvicorn** | `0.54.0` | Servidor ASGI de FastAPI |
| **Playwright** | `1.64.0` | Automatización del navegador Chromium para scraping |
| **PyMongo** | `4.19.0` | Driver de MongoDB, consultas, índices y transacciones |
| **dnspython** | `2.9.0` | Resolución DNS para cadenas MongoDB `mongodb+srv://` |
| **Pydantic** | `2.14.1` | Contratos de datos, esquemas de respuesta y validación de hallazgos |
| **OpenAI Python SDK** | `3.36.1` | Creación de embeddings y llamadas a Responses API |
| **MongoDB Atlas** | Servicio gestionado | Persistencia documental en la nube |
| **HTML, CSS, JavaScript** | Nativos del navegador | Interfaz web, estado, exportación y SVG interactivo |
| **SVG** | Nativo del navegador | Dibujar puntos y relaciones del mapa semántico |

### Dependencias transitivas y de soporte

| Dependencia | Función en el entorno |
|---|---|
| `starlette` | Infraestructura ASGI sobre la que se construye FastAPI |
| `anyio` | Operaciones de concurrencia utilizadas por dependencias ASGI |
| `h11` | Manejo del protocolo HTTP |
| `click` | Utilidades CLI de dependencias |
| `greenlet`, `pyee` | Soporte de ejecución y eventos requerido por Playwright |
| `pydantic_core` | Motor de validación utilizado por Pydantic |
| `annotated-types`, `annotated-doc`, `typing_extensions`, `typing-inspection` | Tipado y metadatos de anotaciones |
| `idna` | Procesamiento de nombres de dominio |
| `opentelemetry-api` | API de instrumentación disponible entre las dependencias |

No toda dependencia de `requirements.txt` es una librería invocada directamente por el proyecto: algunas son **dependencias transitivas**.

### Biblioteca estándar de Python utilizada

- **`json`:** serializar documentos y cuerpos de solicitudes.
- **`re`:** expresiones regulares y extracción de formatos.
- **`decimal.Decimal`:** convertir contadores abreviados evitando errores innecesarios de punto flotante.
- **`datetime`:** fechas de extracción y generación en UTC.
- **`hashlib.sha256`:** huellas de contenido para deduplicación y vigencia.
- **`uuid`:** identificadores de ejecuciones o intentos de análisis.
- **`math`:** normas de vectores, producto escalar, valores propios y operaciones trigonométricas del PCA.
- **`itertools.combinations`:** generar pares de publicaciones sin repetir combinaciones.
- **`unicodedata`:** normalización Unicode NFC de citas para validar evidencias.
- **`fcntl`:** bloqueo del perfil de Chromium entre procesos en Linux.
- **`pathlib`, `os`, `logging`, `copy`:** rutas, configuración, diagnóstico y estructuras de datos.

### ¿Por qué no React ni una biblioteca de gráficos pesada?

La interfaz utiliza **JavaScript vanilla** y SVG. Esto mantiene una arquitectura ligera y evita añadir un framework o un motor gráfico complejo para una visualización de **hasta diez puntos**. La proyección PCA también se calcula en Python, sin requerir NumPy ni scikit-learn para esta implementación.

## 🗂️ Estructura del repositorio

```text
media-scraper/
├── backend/
│   ├── main.py                 # FastAPI, rutas y frontend estático
│   ├── scraper.py              # Extracción TikTok con Playwright
│   ├── session.py              # Perfil Chromium persistente + bloqueo Linux
│   ├── demo.py                 # Capturas locales para demostración
│   ├── manage.py               # Comandos de sesión y capturas
│   ├── normalizer.py           # Normalización de perfiles y publicaciones
│   ├── database.py             # Cliente y configuración MongoDB Atlas
│   ├── repository.py           # Persistencia con transacciones y upserts
│   ├── presentation.py         # Presentación de resultados en consola
│   ├── stored_profiles.py      # Lectura de perfiles almacenados
│   ├── embedding_repository.py # Lectura, vigencia y almacenamiento vectorial
│   ├── embeddings.py           # Embeddings con OpenAI + coseno
│   ├── embedding_routes.py     # Endpoints REST de embeddings
│   ├── semantic_projection.py  # PCA determinista en dos dimensiones
│   ├── semantic_routes.py      # Endpoints de mapa, interpretación y OCEAN
│   ├── semantic_analysis.py    # Interpretación textual y persistencia
│   ├── structured_analysis.py  # JSON Schema restringido y fragmentos literales
│   ├── ocean_analysis.py       # Señales lingüísticas de cinco dimensiones
│   └── analysis_errors.py      # Diagnósticos seguros de errores OpenAI
├── frontend/
│   ├── index.html              # Secciones General, Estadísticas, Big Five
│   ├── style.css               # Diseño responsive y componentes
│   ├── script.js               # Perfiles, estadísticas, exportación JSON/CSV
│   └── big-five.js             # Perfil seleccionado, mapa SVG y OCEAN
├── tests/                      # Unitarias, regresión, UI simulada
├── docs/
│   ├── big-five-verification.md
│   └── openai-evidence-followup.md
├── main.py                     # Herramienta de consola histórica
├── start.sh                    # Arranque de FastAPI
├── requirements.txt            # Dependencias fijadas
├── .gitignore
├── .venv/                      # Entorno virtual: ignorado por Git
├── .media-scraper/             # Sesión y capturas privadas: ignoradas
└── README.md
```

## 🚀 Inicio rápido

### Requisitos

- Sistema Linux (desarrollado en **Zorin OS**).
- Python 3.12 compatible con el entorno del proyecto.
- Internet para consultar TikTok y conectar MongoDB Atlas y OpenAI.
- Git y `pip`.
- MongoDB Atlas con usuario de base, cadena de conexión e IP autorizada.
- Credenciales de OpenAI API para las operaciones de IA (con facturación separada de ChatGPT).

### Clonar el proyecto

```bash
git clone https://github.com/Wotklaus/media-scraper.git
cd media-scraper
git switch feature/setup-inicial
```

> La rama **`main`** es la rama predeterminada del repositorio. Esta documentación corresponde a **`feature/setup-inicial`**, que contiene los módulos de IA. No reemplazar la rama equivocada al integrar cambios.

### Crear el entorno e instalar dependencias

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

### Configuración local

Crear el archivo **`backend/.env`** (sin publicarlo en Git):

```dotenv
MONGODB_URI=mongodb+srv://USUARIO:CLAVE@CLUSTER.example.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=media_scraper
OPENAI_API_KEY=TU_CLAVE_PRIVADA_DE_OPENAI
```

La URI anterior es ilustrativa. Las credenciales reales se configuran únicamente en el equipo de ejecución. Verificar que Atlas permita la IP pública desde la cual se conecta el equipo.

### Preparar la sesión de TikTok cuando sea necesario

```bash
.venv/bin/python -m backend.manage session
```

Se abre Chromium visible con un perfil exclusivo de la aplicación, para realizar la autenticación manual. El estado se almacena en `.media-scraper/chromium/`. La sesión puede expirar; la herramienta no elude CAPTCHA ni promete acceso a todo el contenido.

### Iniciar Media Scraper

```bash
bash start.sh
```

Abrir en Brave u otro navegador:

**http://127.0.0.1:8000**

FastAPI ofrece documentación OpenAPI automática en:

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/openapi.json`

Para detener: **`Ctrl + C`** en la terminal del servidor.

### Modo demostración

Se puede capturar un perfil real autorizado para utilizarlo posteriormente sin volver a consultar TikTok:

```bash
.venv/bin/python -m backend.manage capture USERNAME --authorized
```

La captura se guarda en `.media-scraper/captures/` y es distinta de los datos vivos. Las rutas de modo `demo` leen esa captura sin ejecutar TikTok; no son una consulta nueva.

## 🕷️ Extracción de datos de TikTok

### ¿Por qué Playwright?

TikTok es una aplicación web dinámica: parte de su información se renderiza o se solicita mediante JavaScript. **Playwright controla un navegador real** y permite inspeccionar la información pública disponible después de la navegación.

En `backend/scraper.py` se implementan funciones como `validate_username`, `get_embedded_json`, `extract_profile_data`, `get_profile_video_cards`, `extract_video_details`, `extract_video_comments`, `extract_latest_videos` y `scrape_profile`.

Se combinan técnicas de lectura del **DOM** y estructuras de datos **JSON incrustadas**, cuando están disponibles. La extracción funciona sobre los resultados accesibles para el navegador y sus condiciones de sesión.

### Flujo de una búsqueda

1. El usuario introduce un `username` en la sección **General**.
2. JavaScript ejecuta `fetch()` hacia `GET /api/profile/{username}?mode=real`.
3. FastAPI llama a `scrape_profile(username)`.
4. Playwright abre Chromium en modo headless utilizando el perfil de sesión del proyecto.
5. El extractor recupera atributos de cuenta, hasta diez publicaciones accesibles y métricas recuperables.
6. Cada video se procesa por separado; los errores individuales no deben ocultar todos los resultados anteriores.
7. El normalizador transforma los datos y MongoDB registra la extracción.
8. El frontend muestra el perfil y actualiza las estadísticas.

**Importante:** "hasta diez" es un **límite de consulta**, no una garantía de obtener exactamente diez videos. Algunos perfiles pueden devolver perfil/biografía/métricas, pero **cero publicaciones recuperadas** porque TikTok no entrega las tarjetas o los datos necesarios. Esto es una **extracción parcial**, no prueba de ausencia de publicaciones en la cuenta.

### Sesión persistente de Chromium

`backend/session.py` utiliza:

- `launch_persistent_context`: conserva el estado de autenticación local de Chromium.
- `fcntl.flock`: impide que dos procesos usen simultáneamente el mismo perfil.
- Carpeta privada `.media-scraper/`: no debe versionarse.

No se automatizan verificaciones de identidad ni se reutiliza el perfil personal de Brave.

### Diferencia entre conteos reportados y datos recuperados

Si una publicación muestra **120 comentarios** pero el scraper solo consigue **4 comentarios individuales**, la base diferencia:

- `metrics.comments_count = 120`: cifra que mostró TikTok.
- `retrieved_comments_count = 4`: documentos de comentarios efectivamente obtenidos.
- `comments_complete = null`: no es posible asegurar que se recuperaron todos.

De igual forma, una métrica desconocida se guarda como `null`, no como `0` inventado.

## 🔄 Normalización y mapeo de datos

El código separa **extracción** de **persistencia** mediante `normalize_profile(...)` en `backend/normalizer.py`.

### ¿Qué es un mapeo?

Es la regla que transforma un campo de entrada en un atributo del documento de salida. Ejemplo: `videos[].id` se convierte en `publications[].publication_id` y se trata como **cadena de texto** para no perder precisión.

### Mapeo del perfil

| Campo de origen | Documento normalizado | Regla |
|---|---|---|
| `username` | `profile.username` | Cadena obligatoria |
| `nickname` | `profile.nickname` | Nombre visible |
| `bio` | `profile.bio` | Biografía accesible |
| `avatar_url` | `profile.avatar_url` | URL del avatar |
| `url` | `profile.url` | Enlace del perfil |
| `followers` | `profile.metrics.followers` | Conversión de contador |
| `following` | `profile.metrics.following` | Conversión de contador |
| `likes` | `profile.metrics.likes` | Conversión de contador |
| `id`, `secUid` | `profile.id`, `profile.secUid` | IDs preservados como texto si existen |

El repositorio añade `username_key = username.casefold()`: clave uniforme para reconocer la misma cuenta aunque cambien mayúsculas/minúsculas.

### Mapeo de publicaciones

| Campo del scraper | Campo MongoDB |
|---|---|
| `videos[].id` | `publication_id` |
| Nombre del perfil | `profile_username` |
| `videos[].title` | `description` |
| `videos[].url` | `url` |
| `videos[].type` | `type` |
| `videos[].preview_url` | `preview_url` |
| `videos[].views` | `metrics.views` |
| `videos[].likes` | `metrics.likes` |
| `videos[].comments` | `metrics.comments_count` |
| `videos[].shares` | `metrics.shares` |
| `videos[].saves` | `metrics.saves` |
| `len(videos[].comments_list)` | `retrieved_comments_count` |

### Mapeo de comentarios

Los comentarios recuperados se guardan con `publication_id`, `profile_username`, `comment_id` (si lo suministra TikTok), `username`, `text` y métricas disponibles. Si falta el ID oficial, se genera una identidad local de deduplicación basada en publicación, autor y texto; **no se presenta como ID oficial de TikTok**.

### Conversión de contadores

El normalizador convierte abreviaturas usando `Decimal`:

| Valor mostrado | Representación aproximada |
|---|---:|
| `9261` | `9261` |
| `14.5K` | `14500` |
| `398.8K` | `398800` |
| `1.2M` | `1200000` |

Cuando una cifra es abreviada, la transformación conserva solo la precisión del dato mostrado por TikTok.

### Ejemplo didáctico: documento normalizado

```json
{
  "publication_id": "7699212729617485076",
  "profile_username": "perfil_ejemplo",
  "description": "Una explicación sobre Bitcoin y el mercado",
  "url": "https://www.tiktok.com/@perfil_ejemplo/video/7699212729617485076",
  "metrics": {
    "views": 12500,
    "likes": 860,
    "comments_count": null,
    "shares": 32,
    "saves": null
  },
  "retrieved_comments_count": 0,
  "comments_status": "not_recovered",
  "comments_complete": null
}
```

*Documento sintético de ejemplo; no representa una publicación real consultada.*

## 🍃 Persistencia en MongoDB Atlas

### ¿Por qué una base de datos documental?

MongoDB permite trabajar con documentos BSON similares a JSON, adecuados para datos de redes sociales donde algunos atributos y métricas pueden estar ausentes. Además, el sistema necesita **conservar estados de perfiles, relaciones lógicas entre publicaciones e historial de consultas**.

**Base utilizada:** `media_scraper`.

### Colecciones

| Colección | Propósito | Identificador o vínculo clave |
|---|---|---|
| `profiles` | Datos más recientes de cada cuenta | `username_key` |
| `publications` | Publicaciones y métricas observadas | `publication_id`, `profile_username` |
| `comments` | Comentarios individuales recuperados | `publication_id`, `identity_key` |
| `extraction_runs` | Historial y snapshot de cada consulta real | `run_id` |
| `embeddings` | Vectores generados por versión textual | `publication_id`, `model`, `content_hash` |
| `semantic_analyses` | Interpretación temática y comunicativa validada | `profile_id`, `content_hash`, `model`, `prompt_version` |
| `ocean_analyses` | Indicadores lingüísticos OCEAN validados | Misma identidad conceptual, separada por colección/prompt |
| `big_five_evaluations` | Contrato de lectura para cuestionarios validados, independiente del análisis OCEAN | `profile_username` |

La colección `big_five_evaluations` es una **interfaz de lectura opcional**; no se llena automáticamente al analizar TikTok. Su panel anterior fue retirado de la interfaz principal.

### Modelo lógico

```mermaid
erDiagram
    PROFILES ||--o{ PUBLICATIONS : tiene
    PUBLICATIONS ||--o{ COMMENTS : incluye
    PROFILES ||--o{ EXTRACTION_RUNS : historico
    PUBLICATIONS ||--o{ EMBEDDINGS : representa
    PROFILES ||--o{ SEMANTIC_ANALYSES : interpretacion
    PROFILES ||--o{ OCEAN_ANALYSES : senales
```

Son **relaciones lógicas por identificadores**; MongoDB no aplica automáticamente claves foráneas como una base SQL relacional.

### Índices y unicidad

En `backend/repository.py` se crean índices únicos:

```python
db["profiles"].create_index("username_key", unique=True)
db["publications"].create_index("publication_id", unique=True)
db["comments"].create_index(
    [("publication_id", 1), ("identity_key", 1)],
    unique=True
)
db["extraction_runs"].create_index("run_id", unique=True)
```

En `embeddings` hay un índice compuesto único por:

```text
(publication_id, model, content_hash)
```

### ¿Cómo funciona el `upsert`?

```python
db["profiles"].update_one(
    {"username_key": username.casefold()},
    {"$set": profile_data},
    upsert=True
)
```

- Si no existe ese perfil: **lo inserta**.
- Si existe: **actualiza** sus campos observados.
- No crea una cuenta duplicada por cada consulta.

El repositorio real utiliza además `$setOnInsert` para preservar `first_seen_at`, y campos como `last_seen_at` y `last_run_id`.

### Historial y transacciones

El sistema registra cada consulta real en `extraction_runs` con `run_id`, fecha UTC, hash del payload y snapshot. Se utiliza `with_transaction` y `WriteConcern('majority')` para agrupar las escrituras correspondientes a una extracción.

**Idempotencia:** volver a procesar **el mismo `run_id` y contenido** no debe duplicar la ejecución; una consulta nueva recibe otro `run_id`. Esto distingue **reintentar una operación** de **registrar una observación nueva**.

No se eliminan automáticamente las publicaciones anteriores si una nueva consulta obtiene menos videos. Una extracción con cero resultados no equivale a borrar datos históricos.

## 🧬 Embeddings de las publicaciones

### Concepto

Un embedding convierte un texto en un vector de valores reales. En este proyecto se utiliza:

| Aspecto | Valor implementado |
|---|---|
| Modelo | `text-embedding-3-small` |
| Dimensiones | **1536** |
| Entrada | Descripción textual de una publicación |
| Salida | Vector numérico (`float[]`) |
| Límite de generación | **1 a 10 publicaciones** por solicitud |
| Proveedor | OpenAI API |
| Momento de generación | **Solo al pulsar el botón** |
| Persistencia | Colección `embeddings` |

Ejemplo **ilustrativo** (no son valores reales):

```text
"¿Cómo se comporta el precio de Bitcoin?"
              │
              ▼
       text-embedding-3-small
              │
              ▼
[ 0.018, -0.102, 0.233, ..., -0.047 ]
           1536 valores
```

**Justificación:** el vector permite comparar la **proximidad semántica** de descripciones sin depender exclusivamente de coincidencias literales de palabras. No interpreta por sí solo sentimientos, identidad ni personalidad.

### Flujo técnico real

```mermaid
flowchart LR
    Click["Botón Generar embeddings"] --> Read["MongoDB: últimas 10 publicaciones"]
    Read --> Empty{"¿Descripción no vacía?"}
    Empty -->|No| Skip["skipped"]
    Empty -->|Sí| Hash["SHA-256 de descripción"]
    Hash --> Exists{"¿Vector vigente ya existe?"}
    Exists -->|Sí| Reuse["reused · sin costo"]
    Exists -->|No| OpenAI["OpenAI embeddings.create"]
    OpenAI --> Valid["Verificar dimensión y finitud"]
    Valid --> Save["MongoDB · embeddings"]
    Save --> Generated["generated"]
```

La identidad de un embedding consta de:

```text
publication_id + model + content_hash
```

`content_hash = SHA256(descripción.strip())`.

Si la descripción no cambia y se utiliza el mismo modelo, el embedding se **reutiliza**. Si cambia el texto, el anterior se conserva como historial, pero deja de ser considerado **vigente** para la descripción nueva.

### Campos del documento vectorial

```json
{
  "publication_id": "ID_DE_TIKTOK",
  "profile_username": "username",
  "model": "text-embedding-3-small",
  "text": "Descripción textual normalizada",
  "content_hash": "HASH_SHA256",
  "vector": [0.018, -0.102, 0.233],
  "generated_at": "FECHA_UTC"
}
```

*Esquema simplificado: `vector` tendría exactamente **1536 elementos**, no tres; `generated_at` se almacena como fecha BSON.*

### La respuesta de generación

```json
{
  "username": "username",
  "model": "text-embedding-3-small",
  "processed": 2,
  "generated": 1,
  "reused": 1,
  "failed": 0,
  "skipped": 0,
  "results": [
    {"publication_id": "ID_A", "status": "generated"},
    {"publication_id": "ID_B", "status": "reused"}
  ]
}
```

*Respuesta de ejemplo, no procedente de una solicitud real.*

### Por qué no se generan automáticamente

Una extracción de TikTok debe poder funcionar incluso cuando OpenAI no está disponible o no se desean realizar gastos. Esta separación facilita pruebas, reduce acoplamiento y evita facturación involuntaria.

### Vigencia del vector

La vista verifica:

1. Correspondencia con el perfil.
2. Coincidencia de `publication_id`.
3. Coincidencia de modelo.
4. Coincidencia del hash de la descripción actual.
5. Longitud de 1536 componentes y validez numérica.

Por eso la interfaz distingue **publicaciones disponibles**, **embeddings vigentes** y **pendientes**.

## 📐 Mapa semántico: PCA

### El problema de las 1536 dimensiones

Un embedding contiene 1536 números. No es posible dibujarlo literalmente sobre una pantalla bidimensional. Por ello, el backend implementa **Análisis de Componentes Principales (PCA)** y devuelve un par de coordenadas por publicación.

**PCA** busca direcciones de máxima variación de los vectores centrados. Conserva una aproximación de la estructura de dispersión, no toda la información original.

### Procedimiento matemático

Para **n** publicaciones y **d = 1536** dimensiones, partimos de una matriz de vectores:

$$
X \in \mathbb{R}^{n \times 1536}
$$

1. Calcular la media por dimensión: $\mu_j = \frac{1}{n}\sum_{i=1}^{n}x_{ij}$.
2. Centrar los vectores: $X_c = X - \mu$.
3. Construir la **matriz de Gram** pequeña:

$$
G = X_c X_c^{\mathsf{T}} \quad \in \mathbb{R}^{n\times n}
$$

4. Calcular valores y vectores propios de $G$ mediante el **método de Jacobi** para matrices simétricas.
5. Ordenar los componentes por valor propio y obtener las dos coordenadas principales de cada publicación.
6. Calcular la **proporción de varianza explicada** por cada componente.

$$
\text{Varianza conservada} = 100\,(r_1 + r_2)\,\%
$$

Donde $r_1$ y $r_2$ son las proporciones de varianza explicada de las primeras dos componentes.

### ¿Por qué una matriz de Gram y Jacobi?

**En nuestro caso n ≤ 10.** Resolver un problema de valores propios de tamaño **10 × 10** es más razonable que formar una matriz de covarianza **1536 × 1536**. El código de `backend/semantic_projection.py` implementa esta estrategia directamente en Python y **no depende de NumPy o scikit-learn**.

### Determinismo

No se aplican posiciones aleatorias ni un algoritmo de fuerzas para mover los puntos. La implementación fija la orientación de los ejes para producir resultados reproducibles cuando no cambian los vectores.

### ¿Qué representa cada elemento del mapa?

| Elemento | Interpretación |
|---|---|
| Punto | Una publicación con embedding vigente |
| Posición X/Y | Coordenadas PCA del vector |
| Tamaño del punto | Número de relaciones dibujadas del conjunto seleccionado |
| Línea | Par perteneciente al top cinco con coseno ≥ 0.50 |
| Color/resaltado | Publicación seleccionada o relacionada |
| Panel lateral | Extracto y enlace a la publicación |
| Varianza conservada | Fracción de dispersión captada por las primeras dos componentes |

El umbral **0.50** es una **regla de visualización** de conexiones; no implica significación estadística ni certifica que las publicaciones sean del mismo tema.

**Limitación fundamental:** la distancia visible en el plano de PCA **no es idéntica** a la similitud coseno calculada en las 1536 dimensiones. Para ordenar publicaciones, el sistema usa **el coseno original**, no la distancia del gráfico.

### Caso con pocas publicaciones

- **0 vectores:** mapa vacío con mensaje informativo.
- **1 vector:** punto único en el origen.
- **2 vectores:** representación de dos puntos; no se fuerza artificialmente una nube.
- **Vectores iguales:** los puntos pueden superponerse; existen botones numerados para seleccionarlos.

## 📏 Similitud coseno

### ¿Qué mide?

La similitud coseno compara la **dirección** de dos vectores en un espacio de muchas dimensiones. Es una medida de semejanza matemática, no un porcentaje de certeza de una IA.

Para dos embeddings $\mathbf{a}$ y $\mathbf{b}$:

$$
\operatorname{sim}_{\cos}(\mathbf{a},\mathbf{b})=
\frac{\mathbf{a}\cdot\mathbf{b}}{\lVert\mathbf{a}\rVert_2\;\lVert\mathbf{b}\rVert_2}
$$

Con:

$$
\mathbf{a}\cdot\mathbf{b}=\sum_{i=1}^{1536}a_i b_i
\qquad
\lVert\mathbf{a}\rVert_2=\sqrt{\sum_{i=1}^{1536}a_i^2}
$$

### Interpretación

| Valor | Lectura correcta |
|---|---|
| Cerca de `1` | Direcciones vectoriales próximas, usualmente contenido semejante |
| Cerca de `0` | Direcciones aproximadamente ortogonales |
| Cerca de `-1` | Direcciones opuestas en la representación matemática |

La relación entre un valor particular (por ejemplo **0.81**) y una categoría humana como «mismo tema» **no está calibrada universalmente**. No debe decirse «81 % de precisión» ni «81 % de personalidad».

### Ejemplo matemático sencillo (2D, ilustrativo)

Sean $\mathbf{a}=(1,0)$ y $\mathbf{b}=(0.8,0.6)$.

Ambas normas son 1, por lo que:

$$
\operatorname{sim}_{\cos}(\mathbf{a},\mathbf{b})=\frac{1(0.8)+0(0.6)}{1\cdot1}=0.8
$$

**En el proyecto, el cálculo real utiliza las 1536 componentes.**

### Implementación

`backend/embeddings.py` contiene `cosine_similarity`:

- Rechaza vectores vacíos o de dimensiones diferentes.
- Verifica que todos los valores sean numéricos y finitos.
- Rechaza vectores de norma cero.
- Normaliza por la norma euclidiana y utiliza `math.fsum` para una suma más estable.
- Acota el resultado final al intervalo matemático `[-1, 1]`.

`backend/semantic_routes.py` calcula los pares con `itertools.combinations`, los ordena por similitud **descendente** y devuelve los **cinco primeros**, sin duplicar pares A-B / B-A.

Para n = 10 publicaciones se pueden formar:

$$
\binom{10}{2}=\frac{10\cdot9}{2}=45\text{ pares}
$$

El sistema evalúa los pares válidos y muestra hasta **cinco** con mayor similitud. No hay nuevas llamadas a OpenAI para comparar embeddings existentes.

## 🤖 Interpretación de contenido con OpenAI

### Diferencia entre embeddings y un modelo generativo

| Embeddings | Modelo generativo |
|---|---|
| Produce un vector numérico | Produce texto estructurado |
| Permite calcular relaciones semánticas | Resume e interpreta contenido suministrado |
| `text-embedding-3-small` | `gpt-5.4-mini-2026-03-17` |
| Una entrada textual → 1536 valores | Conjunto de descripciones → JSON con hallazgos |
| Se almacena en `embeddings` | Se almacena en `semantic_analyses` |

El análisis generativo **no es necesario** para calcular PCA ni similitud coseno: son procedimientos independientes.

### ¿Qué se envía al modelo?

- Hasta diez descripciones no vacías del **perfil seleccionado**.
- Una referencia corta por publicación (`p1`…`p10`).
- Una selección de fragmentos **literales** (`evidence_quotes`) extraídos de cada descripción.
- Instrucciones de salida estructurada en español.

No se envían las claves API al navegador. Para este análisis no se envían comentarios de terceros, métricas de interacción ni los vectores completos.

### Modelo y parámetros verificados

| Parámetro | Implementación |
|---|---|
| Modelo | `gpt-5.4-mini-2026-03-17` |
| API | `client.responses.create(...)` |
| Formato | `json_schema`, `strict=True` (Structured Outputs) |
| `reasoning.effort` | `none` |
| `max_output_tokens` | `6000` |
| `store` | `False` |
| Límite de entrada del sistema | 24 000 caracteres de descripciones |
| Reintentos SDK | `0` |
| Timeout cliente | `30` segundos |

Los límites y parámetros corresponden al código actual; no constituyen una garantía de precio o disponibilidad futura del modelo.

### Contrato y verificación de evidencias

La respuesta se modela con Pydantic, principalmente con:

- `Interpretation`: `summary`, `themes`, `communication_style`.
- `Finding`: observación textual, `publication_ids`, evidencias.
- `Theme`: nombre del tema, publicaciones relacionadas y evidencias.
- `Evidence`: `publication_id` y fragmento literal `quote`.

**El problema resuelto durante el desarrollo:** permitir que un modelo generativo escribiera citas arbitrarias podía provocar desajustes con los textos originales. El sistema ahora restringe referencias y citas en el propio esquema enviado al modelo.

```mermaid
flowchart TD
    D["MongoDB · descripciones originales"] --> AL["Asignar aliases p1...p10"]
    AL --> F["Construir evidence_quotes literales"]
    F --> SCHEMA["JSON Schema estricto · enums por fuente"]
    SCHEMA --> AI["OpenAI Responses API"]
    AI --> JSON["Comprobar estado y parsear JSON"]
    JSON --> REST["Restaurar aliases a publication_id original"]
    REST --> VAL["Validar cada hallazgo + citas"]
    VAL -->|"Respaldo válido"| SAVE["Guardar en semantic_analyses"]
    VAL -->|"Hallazgo inválido"| DISC["Descartar hallazgo y registrar motivo"]
```

### Alias y restauración de IDs

Los identificadores de TikTok pueden ser cadenas numéricas muy largas. En la solicitud al modelo, el sistema utiliza `p1`, `p2`, etc. Después **restaura exactamente** el ID original antes de validar y persistir, evitando adivinar identificadores.

El validador comprueba:

1. La publicación referenciada existe entre las fuentes del perfil.
2. Los IDs de respaldo no están duplicados ni fuera del conjunto enviado.
3. Cada fuente citada tiene evidencia correspondiente.
4. La cita está presente en **la descripción de esa misma publicación**.
5. Se permiten diferencias de espacios y composición Unicode NFC, no traducciones ni citas inventadas.

### Recuperación parcial conservadora

Si un hallazgo tiene cita inválida, se descarta **el hallazgo completo**. Los otros hallazgos válidos se conservan. Si no existe ningún respaldo verificable, no se inventa una interpretación.

Se registra información técnica sobre intentos, hallazgos recibidos/aceptados/rechazados y categoría del rechazo, sin exponer secretos ni guardar el cuerpo completo del proveedor en los diagnósticos.

### Persistencia y reutilización

La identidad del análisis se deriva de:

```text
profile_id + content_hash + model + prompt_version
```

El hash resume el conjunto de IDs y descripciones. Cuando contenido, modelo y versión de prompt siguen siendo los mismos, la aplicación **recupera el análisis existente**. Esto reduce consumo y evita producir interpretaciones diferentes en cada recarga.

## 🧠 Big Five / OCEAN y señales lingüísticas

### ¿Qué significa Big Five?

El modelo **Big Five**, también conocido por el acrónimo **OCEAN**, organiza rasgos de personalidad en cinco dimensiones. La aplicación utiliza estos cinco nombres como **categorías de observación lingüística**, no como un test de personalidad del creador.

| Dimensión OCEAN | Nombre en interfaz | Señales textuales exploradas |
|---|---|---|
| **O — Openness** | Apertura | Expresiones de curiosidad, novedad, exploración de ideas |
| **C — Conscientiousness** | Responsabilidad | Planificación, organización o compromisos mencionados |
| **E — Extraversion** | Extraversión | Invitaciones a interactuar o conversar |
| **A — Agreeableness** | Amabilidad | Cooperación, agradecimiento o apoyo explícito |
| **N — Neuroticism** | Neuroticismo | Expresiones de preocupación o malestar presentes en el texto |

**Criterio metodológico:** que un texto contenga tristeza, agradecimiento o una invitación a conversar **no demuestra** que su autor posea un determinado rasgo psicológico. El resultado describe **señales en publicaciones**, no atributos personales validados.

### ¿Por qué utilizar OCEAN aquí?

Sirve como un marco conceptual de **cinco categorías estables** para presentar y organizar patrones lingüísticos observables, manteniendo trazabilidad a la fuente de cada hallazgo. Es una **exploración de contenido**, no una evaluación psicométrica.

### ¿Cómo trabaja el módulo?

1. Selecciona el perfil desde Big Five.
2. Recupera sus descripciones almacenadas en MongoDB.
3. El usuario pulsa **«Analizar Big Five»**; sin pulsar, no se genera nada.
4. OpenAI recibe descripciones, referencias cortas y fragmentos de citas válidas.
5. Responde con **cinco dimensiones**, sus indicadores y evidencias, mediante Structured Outputs.
6. `OceanAnalysis` valida cada indicador y elimina los que no tienen respaldo.
7. Guarda el resultado en `ocean_analyses` y lo reutiliza mientras siga vigente.
8. El frontend dibuja las cinco tarjetas y calcula índices de presencia con los conteos verificados.

### Estructura de un indicador

Un `LinguisticIndicator` contiene:

```json
{
  "name": "Apoyo explícito",
  "description": "Se observa lenguaje de acompañamiento en la publicación.",
  "publication_ids": ["ID_PUBLICACION_A"],
  "evidence": [
    {
      "publication_id": "ID_PUBLICACION_A",
      "quote": "Fragmento literal de la descripción"
    }
  ]
}
```

*Ejemplo de estructura; no es un hallazgo real.*

Cada indicador debe tener al menos un ID de publicación y una cita verificable. El backend consolida los IDs de respaldo **sin contar una publicación dos veces dentro de una dimensión**.

### ¿Qué significa el porcentaje de las barras?

**No es una puntuación Big Five.** En la vista se calcula el porcentaje de **publicaciones analizadas que contienen una señal respaldada**:

$$
\operatorname{Presencia}(D) = \frac{N_{\text{publicaciones con señales en }D}}{N_{\text{publicaciones analizadas}}}\times100
$$

**Ejemplo:** si tres de diez publicaciones contienen señales respaldadas en Amabilidad:

$$
\operatorname{Presencia}(A) = \frac{3}{10}\times100 = 30\%.
$$

Esto significa **«señales de esa categoría presentes en 3/10 textos»**, y **no** «la persona es 30 % amable».

La versión actual del frontend calcula el índice directamente a partir de `support_count` y `total_count`. En `backend/ocean_analysis.py`, el campo derivado `presence_index` puede ser `null` cuando hay menos de dos fuentes; la interfaz calcula el porcentaje de presencia igualmente para mostrar todas las tarjetas.

### Estados presentados

| Soporte validado | Estado visual | Interpretación |
|---|---|---|
| 0 publicaciones | `Sin señales identificadas` | El análisis no identificó citas que respalden esa categoría |
| 1 publicación | `Señal aislada` | Existe un caso textual aislado, sin evidencia recurrente |
| ≥ 2 publicaciones | `Señales observadas` | Hay más de una publicación con respaldo verificable |

La pantalla presenta siempre cinco tarjetas, con barras, porcentajes, conteos y desplegables de indicadores/citas. No se llenan con números inventados cuando no hay evidencia.

### ¿Big Five necesita embeddings para ejecutarse?

**No directamente.** El módulo OCEAN **lee descripciones textuales almacenadas**, mientras los embeddings sirven a las operaciones vectoriales de PCA y similitud. Ambos viven en la misma vista y se vinculan al perfil, pero son **flujos técnicos independientes**.

### Reutilización y regeneración

- `GET /api/semantics/{username}/ocean` recupera el resultado vigente sin costo de OpenAI.
- `POST /api/semantics/{username}/ocean` inicia un análisis explícito o reutiliza el ya existente.
- Para **regenerar** un resultado vigente se requiere una acción separada y confirmación de costo (`regenerate` y `confirm_cost`).

### Alcance científico

Los cinco factores OCEAN provienen de la psicología de la personalidad; **la aplicación no administra cuestionarios validados ni estima puntuaciones psicológicas personales con validez clínica**. La clasificación automática de expresiones puede equivocarse o depender del contexto. Por eso las afirmaciones quedan vinculadas a citas y publicaciones concretas.

Esto es una **fortaleza de trazabilidad**: durante la defensa se puede abrir la publicación vinculada a cada indicador y explicar qué texto motivó la categoría.

## 🖥️ Frontend y visualización

### Sección «General»

- Formulario de búsqueda por `username`.
- Avatar, nickname, nombre de usuario, biografía, enlace al perfil.
- Métricas de seguidores, seguidos y me gusta.
- Publicaciones recuperadas con métricas disponibles.
- Exportación de información pública a **JSON** y **CSV**.

### Sección «Estadísticas»

- Rankings de hasta diez publicaciones por visualizaciones o interacciones.
- Conteo de hashtags presentes en las descripciones disponibles.
- Indicadores de interacción; la UI declara:

$$
\text{Interacciones observadas}=\text{likes}+\text{comentarios reportados}+\text{compartidos}+\text{guardados}
$$

Las métricas no disponibles no deben mostrarse como si fueran mediciones confirmadas iguales a cero.

### Sección «Big Five»

- Selector de perfiles almacenados (`nickname` + `username`).
- Tres indicadores: publicaciones disponibles, embeddings vigentes y pendientes.
- Mapa semántico interactivo sobre SVG.
- Panel de embeddings con botón de generación manual.
- Top cinco pares de publicaciones relacionadas.
- Interpretación de contenido con su propio botón.
- Cinco tarjetas OCEAN, barras de presencia y evidencias desplegables.
- Mensajes de estado y reutilización de resultados guardados.

### Detalles visuales del mapa

El SVG utiliza `viewBox` y escala uniforme, sin distorsionar las coordenadas PCA. Al seleccionar un punto:

- Se resalta la publicación actual.
- Se destacan conexiones y publicaciones relacionadas.
- Se muestra una ficha lateral con extracto y enlace externo válido a TikTok.
- El listado de pares también resalta sus coincidencias.

Las relaciones visibles proceden de **similitudes calculadas** y pasan por un umbral visual de coseno ≥ 0.50 entre los cinco pares principales.

## 🔌 API REST documentada

La API expone documentación interactiva mediante FastAPI en `/docs`. La siguiente tabla resume las rutas implementadas en la rama inspeccionada.

### Extracción y datos almacenados

| Método | Ruta | Operación | ¿Efecto? |
|---|---|---|---|
| `GET` | `/api/profile/{username}` | Scraping real por defecto | Consulta TikTok y guarda |
| `GET` | `/api/profile/{username}?mode=real` | Scraping real explícito | Consulta TikTok y guarda |
| `GET` | `/api/profile/{username}?mode=demo` | Leer captura local | No consulta TikTok |
| `GET` | `/api/stored-profiles` | Listar perfiles MongoDB | Solo lectura |
| `GET` | `/api/stored-profiles/{username}/publications` | Publicaciones, estados y relaciones | Solo lectura |

> La ruta `GET /api/profile/{username}` **sí tiene efectos externos y de persistencia** por su diseño actual, aunque utilice GET. No es una consulta inofensiva al servidor: inicia una extracción real. Es una posible mejora de diseño migrarla a un POST de trabajo explícito.

### Embeddings

| Método | Ruta | Función |
|---|---|---|
| `POST` | `/api/embeddings/{username}?limit=10` | Generación manual (1–10 publicaciones) |
| `GET` | `/api/embeddings/{username}?limit=10` | Listar vectores almacenados del perfil, sin generación |
| `GET` | `/api/embeddings/{username}/similarity?first_id=ID1&second_id=ID2` | Comparación coseno exacta entre dos publicaciones vigentes |

### Semántica, interpretación y OCEAN

| Método | Ruta | Función |
|---|---|---|
| `GET` | `/api/semantics/{username}/map` | PCA 2D, varianza y top cinco pares relacionados |
| `GET` | `/api/semantics/{username}/analysis` | Interpretación de contenido guardada |
| `POST` | `/api/semantics/{username}/analysis` | Generar/reutilizar interpretación bajo demanda |
| `GET` | `/api/semantics/{username}/ocean` | Señales OCEAN almacenadas |
| `POST` | `/api/semantics/{username}/ocean` | Generar/reutilizar señales OCEAN bajo demanda |
| `GET` | `/api/semantics/{username}/big-five` | Contrato de lectura para eventual cuestionario validado; no genera nada |

### Ejemplos con `curl`

Consultar perfiles almacenados:

```bash
curl -sS "http://127.0.0.1:8000/api/stored-profiles"
```

Consultar publicaciones de un perfil:

```bash
curl -sS "http://127.0.0.1:8000/api/stored-profiles/zonaatrading/publications"
```

Obtener mapa sin consumir API de OpenAI:

```bash
curl -sS "http://127.0.0.1:8000/api/semantics/zonaatrading/map"
```

Consultar resultados OCEAN ya guardados:

```bash
curl -sS "http://127.0.0.1:8000/api/semantics/zonaatrading/ocean"
```

Obtener interpretación guardada:

```bash
curl -sS "http://127.0.0.1:8000/api/semantics/zonaatrading/analysis"
```

**Solicitudes con costo potencial:** requieren invocación consciente y credenciales de OpenAI configuradas.

```bash
# Generar embeddings que aún no existen para las primeras 10 publicaciones:
curl -sS -X POST "http://127.0.0.1:8000/api/embeddings/zonaatrading?limit=10"

# Solicitar interpretación de contenido:
curl -sS -X POST "http://127.0.0.1:8000/api/semantics/zonaatrading/analysis"

# Solicitar análisis exploratorio OCEAN:
curl -sS -X POST "http://127.0.0.1:8000/api/semantics/zonaatrading/ocean"
```

Regenerar OCEAN vigente **solo tras confirmar conscientemente el costo**:

```bash
curl -sS -X POST \
  "http://127.0.0.1:8000/api/semantics/zonaatrading/ocean" \
  -H "Content-Type: application/json" \
  -d '{"regenerate":true,"confirm_cost":true}'
```

### Ejemplo de mapa (respuesta simplificada)

```json
{
  "profile_id": "perfil_ejemplo",
  "username": "perfil_ejemplo",
  "model": "text-embedding-3-small",
  "method": "centered_pca",
  "limit": 10,
  "points": [
    {
      "publication_id": "ID_A",
      "description": "Descripción breve de A",
      "url": null,
      "x": -0.12,
      "y": 0.04
    },
    {
      "publication_id": "ID_B",
      "description": "Descripción breve de B",
      "url": null,
      "x": 0.12,
      "y": -0.04
    }
  ],
  "related": [
    {
      "first": {"publication_id": "ID_A", "description": "A", "url": null},
      "second": {"publication_id": "ID_B", "description": "B", "url": null},
      "similarity": 0.8
    }
  ],
  "explained_variance_ratio": [1.0, 0.0],
  "rank": 1
}
```

*Formato sintético con valores ilustrativos; las coordenadas y similitudes reales siempre se calculan desde MongoDB.*

### Errores HTTP y estados

| Situación | Comportamiento |
|---|---|
| Perfil no almacenado | `404` en rutas de datos existentes |
| Límite de embeddings fuera de `1…10` | `422` por validación FastAPI |
| Embedding actual ausente en una comparación | `404` |
| Datos de análisis inválidos o demasiado extensos | `422` |
| Análisis concurrente para el mismo conjunto | `409` |
| Cuota/tasa de OpenAI | `429` para ciertos fallos de proveedor |
| Timeout OpenAI | `504` |
| MongoDB inaccesible | `503` |
| Salida de IA no utilizable / error de proveedor | `502` o código controlado correspondiente |

Las respuestas concretas de cada endpoint están definidas en sus funciones y pueden verificarse en `/docs`.

## 💳 Control de consumo y reutilización

### ¿Qué operaciones generan costos de OpenAI?

- **Embeddings:** solamente cuando no existe un vector vigente y se pulsa **Generar embeddings**.
- **Interpretación:** cuando se solicita explícitamente y no hay análisis vigente reutilizable.
- **OCEAN:** cuando se solicita explícitamente y no hay resultado vigente reutilizable; regenerar exige confirmación.

**No hay un precio fijo documentado aquí.** La facturación depende del modelo y del volumen procesado; los precios se consultan en la página oficial de OpenAI.

**ChatGPT Plus y la facturación de la API son servicios distintos.** La aplicación utiliza la API mediante una clave privada del proyecto.

### Política de caché

| Resultado | Clave de vigencia |
|---|---|
| Embedding | `publication_id + model + SHA256(text)` |
| Interpretación | `profile_id + hash(conjunto de IDs/textos) + model + prompt_version` |
| OCEAN | Misma lógica de identidad, colección y versión de prompt propias |

Si el contenido cambia, el resultado anterior puede conservarse como historial, pero el sistema no debe confundirlo con el análisis vigente del nuevo texto.

### Protección frente a duplicados

- Embeddings: índice único y `upsert` con `$setOnInsert`.
- Análisis generativos: un `_id` determinista reserva el trabajo; intentos concurrentes pueden responder `409`.
- No se reintentan automáticamente solicitudes de OpenAI: se limita el riesgo de consumo duplicado después de fallos inciertos.

## 🔐 Validación, trazabilidad y seguridad

### Principios aplicados

1. **Separación de responsabilidades:** scraper, normalizador, repositorio, embeddings y semántica son componentes distintos.
2. **Validación de fuentes:** cada análisis apunta a publicaciones conocidas del perfil.
3. **Referencias auditables:** citas breves deben coincidir con el contenido almacenado.
4. **Control de secretos:** las claves se mantienen en `backend/.env`, fuera del frontend y del control de versiones.
5. **No inventar datos:** los campos desconocidos permanecen desconocidos; las evidencias ausentes no se rellenan artificialmente.
6. **Sin reintentos automáticos pagados:** protege frente a gasto involuntario.
7. **Límites de tamaño:** hasta diez textos y máximo de caracteres para análisis.
8. **Navegación de solo lectura:** selección y recarga no generan análisis.

### Defensa frente a contenido no confiable

Las descripciones provienen de una fuente externa y se consideran **datos**, no instrucciones. Los prompts internos indican al modelo que ignore órdenes incrustadas en las publicaciones. La estructura de salida y las referencias se validan otra vez en el backend.

### Protección de la sesión

`.media-scraper/` contiene datos del navegador y capturas potencialmente sensibles. Debe permanecer fuera del repositorio y con permisos privados. No copiar al README cookies, URI con contraseñas ni tokens de OpenAI.

### Diagnóstico seguro

`backend/analysis_errors.py` distingue situaciones como:

- `authentication`, `rate_limit`, `timeout`, `connection`.
- `model_unavailable`, `invalid_schema`, `output_json`.
- `evidence_reference`, `evidence_coverage`, `evidence_quote`.
- `evidence_missing`, `storage`.

Los errores incorporan referencias técnicas que permiten investigar sin registrar prompts completos, citas, claves ni cuerpos privados del proveedor.

## 🧪 Pruebas y diagnóstico

### Ejecutar pruebas del backend

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -v
```

### Ejecutar pruebas de JavaScript

```bash
node tests/test_big_five.cjs
node tests/test_semantic_dashboard.cjs
```

### Suites especializadas

```bash
.venv/bin/python -m unittest discover -s tests -p test_embeddings.py -v
.venv/bin/python -m unittest discover -s tests -p test_stored_profiles.py -v
.venv/bin/python -m unittest discover -s tests -p test_semantics.py -v
.venv/bin/python -m unittest discover -s tests -p test_ocean.py -v
.venv/bin/python -m unittest discover -s tests -p test_source_evidence.py -v
.venv/bin/python -m unittest discover -s tests -p test_analysis_recovery.py -v
```

**Nota:** algunos tests del navegador requieren Chromium instalado. Los tests semánticos usan mocks y no deben realizar llamadas pagadas. Las cifras de pruebas aprobadas pueden cambiar entre commits; consulta la salida real de cada ejecución.

### Casos relevantes

- Extracción normal y parcial.
- Normalización de contadores y distinción `null`/cero.
- Evitar duplicados de perfiles y publicaciones.
- Reutilización de embeddings sin consumir API.
- Hash y dimensión correctos del vector.
- PCA determinista con vectores idénticos, únicos o múltiples.
- Similitud coseno numéricamente válida.
- IDs de fuentes y citas literales con Unicode NFC.
- Rechazo y recuperación conservadora de resultados parciales.
- Aislamiento de resultados al cambiar A → B → A.
- Ausencia de POST al navegar o recargar.
- Diseño responsive y control con teclado del SVG.

### Problemas conocidos

**Algunos perfiles muestran cero publicaciones, aunque sí se recuperen biografía, avatar y métricas.** Esto puede deberse a contenido no expuesto, estructuras diferentes, restricciones o carga incompleta. No se ha determinado una causa universal ni se garantiza una solución para todos los perfiles. El sistema informa una consulta parcial, **no completa con publicaciones ficticias**.

**El análisis generativo puede no identificar señales respaldadas.** Una salida sin evidencias verificables se considera ausencia de hallazgos o error validado, no motivo para fabricar porcentajes.

## 🎓 Guía para la defensa técnica

### Discurso de presentación (aprox. 90 segundos)

> Media Scraper es una aplicación web basada en una arquitectura cliente-servidor. Utiliza Playwright y Chromium para recuperar información pública accesible de TikTok. FastAPI recibe esos datos, aplica una normalización y los persiste en MongoDB Atlas mediante colecciones separadas para perfiles, publicaciones, comentarios e historial de ejecuciones.
>
> En el frontend se visualizan métricas, rankings y hashtags. El módulo de análisis semántico utiliza OpenAI para generar embeddings de 1536 dimensiones a partir de las descripciones de las publicaciones, bajo demanda. Esos vectores se comparan mediante similitud coseno y se proyectan a dos dimensiones con PCA, calculado localmente en Python.
>
> Adicionalmente, un modelo generativo produce interpretaciones y organiza señales lingüísticas según las cinco dimensiones OCEAN. Los resultados se validan con IDs y citas literales de las publicaciones originales. Los análisis se almacenan y se reutilizan cuando el contenido no cambia, lo que mejora la trazabilidad y reduce costos de API.
>
> La principal contribución es integrar extracción, persistencia, cálculos reproducibles y análisis de lenguaje dentro de un mismo sistema, diferenciando claramente datos observados, relaciones matemáticas e interpretaciones exploratorias.

### Preguntas probables del docente y respuestas fundamentadas

<details>
<summary><strong>1. ¿Por qué utilizar Playwright y no BeautifulSoup?</strong></summary>

Playwright opera sobre Chromium y puede consultar una página dinámica después de ejecutar JavaScript. BeautifulSoup es un parser HTML útil, pero no administra por sí mismo navegación dinámica ni sesión persistente. Playwright se adecua al tipo de interfaz que utiliza TikTok.
</details>

<details>
<summary><strong>2. ¿Por qué FastAPI?</strong></summary>

Ofrece una API REST en Python, validaciones, manejo HTTP y documentación OpenAPI. Permite conectar el scraper y los análisis con un frontend ligero sin mezclar la lógica de interfaz con el acceso a datos.
</details>

<details>
<summary><strong>3. ¿Por qué MongoDB y no MySQL?</strong></summary>

Los documentos de perfiles, publicaciones y análisis tienen campos heterogéneos y opcionales. MongoDB permite conservarlos en BSON, emplear índices únicos y escribir estados actualizados e historiales separados. MySQL también podría implementarlo, pero para este prototipo se eligió un modelo documental adaptable a datos semiestructurados.
</details>

<details>
<summary><strong>4. ¿Qué evita que el mismo usuario se guarde varias veces?</strong></summary>

El campo `username_key` normalizado y su índice único. Los documentos se escriben con `upsert=True`, de modo que se inserta la cuenta si no existe y se actualiza si ya existe. El historial se guarda por separado.
</details>

<details>
<summary><strong>5. ¿Qué diferencia existe entre scraping y embeddings?</strong></summary>

El scraping extrae información desde TikTok. Un embedding transforma una descripción ya almacenada en un vector matemático. Son pasos independientes; no se llama a OpenAI durante la extracción normal.
</details>

<details>
<summary><strong>6. ¿Por qué cada embedding tiene 1536 dimensiones?</strong></summary>

Es la configuración del modelo `text-embedding-3-small` usada por esta implementación. El vector contiene 1536 componentes que representan la descripción en el espacio semántico del modelo.
</details>

<details>
<summary><strong>7. ¿Por qué usar hash SHA-256?</strong></summary>

Para identificar la versión textual de una publicación. El sistema asocia el embedding con `publication_id`, modelo y hash de la descripción. Si el texto no cambia, reutiliza el vector; si cambia, el anterior no debe tratarse como vigente.
</details>

<details>
<summary><strong>8. ¿Por qué PCA y qué representan sus ejes?</strong></summary>

PCA reduce la representación de 1536 dimensiones a dos componentes de máxima variación, útiles para dibujar un mapa. Los ejes son componentes matemáticas y no equivalen a categorías semánticas predefinidas como «trading» o «humor».
</details>

<details>
<summary><strong>9. ¿Por qué matriz de Gram y Jacobi?</strong></summary>

Con hasta diez publicaciones, la matriz de Gram tiene como máximo 10 × 10 elementos, mucho menor que una matriz de 1536 × 1536. Jacobi permite calcular valores propios de la matriz simétrica sin añadir una dependencia numérica pesada.
</details>

<details>
<summary><strong>10. ¿Qué significa un coseno de 0.81?</strong></summary>

Que los vectores tienen direcciones relativamente próximas en el espacio del modelo. No significa 81 % de precisión ni probabilidad de pertenecer al mismo tema. La interpretación requiere contexto y los umbrales no están universalmente calibrados.
</details>

<details>
<summary><strong>11. ¿Por qué la distancia del mapa no coincide exactamente con el coseno?</strong></summary>

La visualización usa dos dimensiones PCA y pierde parte de la información original. El coseno se calcula sobre las 1536 dimensiones para comparar publicaciones. Son dos operaciones matemáticas diferentes.
</details>

<details>
<summary><strong>12. ¿Qué aporta Structured Outputs?</strong></summary>

Obliga al modelo a producir una estructura JSON según un contrato. El backend también verifica IDs, cobertura y citas en sus textos originales, porque una estructura correcta por sí sola no garantiza veracidad.
</details>

<details>
<summary><strong>13. ¿Para qué se utilizan `p1`…`p10`?</strong></summary>

Son referencias cortas que representan IDs reales largos de publicaciones. El backend conserva el mapa de correspondencias, restringe las opciones del modelo y restaura los IDs originales antes de validar y almacenar los resultados.
</details>

<details>
<summary><strong>14. ¿Cómo justificas OCEAN / Big Five?</strong></summary>

Se utiliza como un marco de cinco categorías para organizar señales lingüísticas observables: curiosidad, planificación, interacción social, apoyo y preocupación. No se afirma medir científicamente la personalidad del creador. Cada indicador debe estar respaldado por citas y publicaciones.
</details>

<details>
<summary><strong>15. ¿Qué significa 30 % en Amabilidad?</strong></summary>

Que en el conjunto analizado, el 30 % de las publicaciones presenta al menos una señal lingüística validada en esa categoría; por ejemplo, tres de diez. No afirma que la persona tenga un nivel de amabilidad del 30 %.
</details>

<details>
<summary><strong>16. ¿Por qué OCEAN no depende de los embeddings?</strong></summary>

El modelo generativo analiza descripciones originales para obtener indicadores y citas; los embeddings sirven para la comparación matemática entre publicaciones. Se complementan en la interfaz, pero no son el mismo algoritmo.
</details>

<details>
<summary><strong>17. ¿Cómo evitas pagar varias veces por lo mismo?</strong></summary>

Se guarda una huella del contenido y se reutilizan vectores o análisis vigentes. Los POST de pago requieren acciones explícitas y los GET únicamente consultan resultados. Las llamadas al SDK no se reintentan automáticamente.
</details>

<details>
<summary><strong>18. ¿Por qué algunos perfiles muestran cero publicaciones?</strong></summary>

Porque recuperar perfil y recuperar publicaciones son procesos diferentes. TikTok puede no entregar las tarjetas, limitar la carga o presentar una estructura que el scraper no interprete. La aplicación informa el resultado parcial y no inventa videos para completar diez.
</details>

<details>
<summary><strong>19. ¿Qué partes son deterministas y cuáles dependen de IA generativa?</strong></summary>

Normalización, hash, upsert, similitud coseno y PCA son operaciones programadas y reproducibles sobre los mismos datos. La clasificación e interpretación de lenguaje provienen de OpenAI y se someten a verificaciones posteriores.
</details>

<details>
<summary><strong>20. ¿Cuál es la contribución propia del sistema?</strong></summary>

La integración del flujo completo: navegador automatizado, API, datos normalizados, persistencia transaccional, reutilización de embeddings, PCA de muestra pequeña, validación de evidencias y visualización OCEAN por perfil seleccionado.
</details>

### Demostración recomendada sin gastos

1. Abrir el frontend y mostrar un perfil **ya almacenado**.
2. En General, explicar qué datos procede recuperar y qué significan los valores ausentes.
3. En Estadísticas, ordenar publicaciones y comentar métricas y hashtags.
4. En Big Five, seleccionar un perfil que **ya tenga embeddings y análisis vigentes**.
5. Explicar los **1536 valores vectoriales**, sin mostrarlos íntegramente.
6. Seleccionar un punto del mapa y ver sus conexiones.
7. Mostrar un par con similitud coseno calculada.
8. Abrir evidencias del análisis OCEAN y el enlace a la publicación original.
9. Recargar y demostrar que aparecen los mismos datos sin generar nuevos análisis.
10. Enseñar colecciones e índices en MongoDB Atlas y la documentación `/docs` de FastAPI.

**Evita solicitar una extracción nueva o un análisis pagado durante una demostración si ya existen registros adecuados.**

## ⚠️ Limitaciones conocidas y alcance

- La plataforma obtiene información **accesible** de TikTok; no garantiza acceso a perfiles restringidos ni a todas las publicaciones.
- Algunos perfiles devuelven **0 videos** aunque el perfil sí se lea. No se ha establecido una solución universal.
- Se analizan como máximo **diez publicaciones por perfil** en los flujos principales actuales.
- Las métricas abreviadas son aproximadas y algunos datos pueden ser `null`.
- Un comentario no recuperado no significa que la publicación no tenga comentarios.
- Los embeddings se generan de **descripciones textuales**, no del audio ni de imágenes del video.
- El PCA proyecta a 2D y pierde parte de la información de alta dimensión.
- La similitud coseno compara vectores, no mide por sí sola identidad de temas, veracidad o afinidad psicológica.
- La interpretación generativa puede ser incorrecta; las citas verificadas mitigan la atribución de fuentes inexistentes, pero no garantizan la verdad de toda interpretación.
- El módulo OCEAN registra **señales textuales**, no puntuaciones psicométricas ni diagnósticos de personas.
- El proyecto se ejecuta **localmente**; no incluye despliegue público endurecido, autenticación web multiusuario ni sistema de colas.

### Posibles evoluciones

- Mejorar tolerancia del scraper a variaciones de TikTok sin comprometer la integridad de datos.
- Ampliar corpus y diferenciar contenido de publicaciones audiovisuales y descripciones.
- Incorporar clustering semántico y métricas comparativas con evaluación empírica.
- Añadir una cola explícita de procesos largos y políticas de observabilidad.
- Evaluar costos de llamadas y estimar consumo mediante tokens.
- Añadir comparaciones temporales longitudinales de un mismo perfil.
- Establecer un método de validación humana de temas y señales lingüísticas.

## 📚 Bibliografía y glosario

### Documentación técnica

- [FastAPI — Documentación oficial](https://fastapi.tiangolo.com/)
- [Playwright Python](https://playwright.dev/python/docs/intro)
- [Playwright — Persistent browser context](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)
- [MongoDB — Documentación](https://www.mongodb.com/docs/)
- [PyMongo — Documentación](https://pymongo.readthedocs.io/)
- [OpenAI API — Embeddings](https://platform.openai.com/docs/guides/embeddings)
- [OpenAI API — Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- [OpenAI API — Modelos](https://platform.openai.com/docs/models)
- [GitHub — Escritura Markdown y diagramas Mermaid](https://docs.github.com/es/get-started/writing-on-github)

### Bases teóricas

- **PCA:** Jolliffe, I. T. (2002). *Principal Component Analysis* (2.ª ed.). Springer.
- **Método de Jacobi:** Golub, G. H., & Van Loan, C. F. (2013). *Matrix Computations* (4.ª ed.). Johns Hopkins University Press.
- **Representación vectorial / recuperación:** Manning, C. D., Raghavan, P., & Schütze, H. (2008). *Introduction to Information Retrieval*. Cambridge University Press.
- **Big Five:** John, O. P., Naumann, L. P., & Soto, C. J. (2008). *Paradigm Shift to the Integrative Big Five Trait Taxonomy*. En *Handbook of Personality: Theory and Research*.

### Glosario

| Término | Definición breve |
|---|---|
| **Scraping** | Extracción automatizada de información desde páginas web |
| **DOM** | Representación estructurada de los elementos de una página |
| **API REST** | Interfaz HTTP para solicitar y modificar recursos |
| **JSON / BSON** | Formatos estructurados de intercambio / almacenamiento documental |
| **Upsert** | Insertar un documento si no existe o actualizarlo si existe |
| **Índice único** | Restricción que previene identidades duplicadas |
| **Idempotencia** | Repetir una operación identificada sin producir duplicados indebidos |
| **Embedding** | Vector numérico que representa información textual |
| **SHA-256** | Función hash utilizada para identificar contenido |
| **PCA** | Reducción lineal de dimensiones conservando varianza |
| **Matriz de Gram** | Matriz de productos escalares entre vectores |
| **Coseno** | Semejanza direccional entre vectores |
| **Structured Outputs** | Salida JSON restringida por un esquema |
| **OCEAN** | Acrónimo de cinco dimensiones Big Five usadas como categorías exploratorias |
| **Evidencia literal** | Fragmento textual que aparece en la publicación citada |
| **Análisis vigente** | Resultado correspondiente a la versión actual del contenido/modelo/prompt |

---

<div align="center">

**Media Scraper — Social Media Analytics**

*Extracción, datos persistentes, representación vectorial y análisis lingüístico trazable en una misma plataforma.*

**Documento preparado para la implementación de `feature/setup-inicial` · Octubre de 2026**

</div>
