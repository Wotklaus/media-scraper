"""Dedicated local Chromium profile with a process-safe lock (Linux)."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright

PRIVATE_DIR = Path(__file__).resolve().parent.parent / ".media-scraper"


class SessionBusyError(RuntimeError):
    pass


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


@contextmanager
def profile_lock():
    root = private_directory(PRIVATE_DIR)
    # Keep the lock file: unlinking it would allow competing locks.
    fd = os.open(root / "session.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SessionBusyError(
                "La sesión está en uso. Espera a que termine la consulta "
                "o cierra la configuración inicial."
            ) from None
        yield private_directory(root / "chromium")
    finally:
        os.close(fd)


@contextmanager
def persistent_context(*, headless=True):
    with profile_lock() as profile:
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile), headless=headless,
                    accept_downloads=False,
                )
                try:
                    yield context
                finally:
                    context.close()
        except PlaywrightError:
            # Driver errors can include URLs or private profile information.
            raise RuntimeError(
                "No se pudo cargar TikTok o iniciar Chromium. Comprueba la conexión, "
                "la instalación de Chromium y configura la sesión si es necesario."
            ) from None


def configure_session():
    with persistent_context(headless=False) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded", timeout=30000)
        print("Inicia sesión manualmente en tu cuenta dentro de Chromium.")
        print("Si TikTok pide una verificación, resuélvela manualmente o cancela.")
        input("Cuando hayas terminado, pulsa ENTER aquí para guardar y cerrar: ")
