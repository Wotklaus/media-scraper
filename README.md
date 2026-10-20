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
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
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
