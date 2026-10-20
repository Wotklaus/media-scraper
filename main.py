
import re
import json

from playwright.sync_api import (
    sync_playwright,
    Error,
    TimeoutError as PlaywrightTimeoutError,
)


def validar_username(entrada):
    username = entrada.strip().removeprefix("@")

    if not re.fullmatch(r"[A-Za-z0-9._]{1,24}", username):
        raise ValueError("El username no tiene un formato válido.")

    return username


def obtener_texto(page, selector):
    elemento = page.locator(selector).first

    try:
        return elemento.inner_text(timeout=5000).strip()
    except PlaywrightTimeoutError:
        return None


def extraer_perfil(page, username):
    print("\nEsperando los datos del perfil...")

    try:
        page.locator(
            '[data-e2e="user-title"]'
        ).first.wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError:
        print("Aviso: no se encontró el título del perfil.")

    perfil = {
        "username": username,
        "nickname": obtener_texto(
            page, '[data-e2e="user-title"]'
        ),
        "followers": obtener_texto(
            page, '[data-e2e="followers-count"]'
        ),
        "following": obtener_texto(
            page, '[data-e2e="following-count"]'
        ),
        "likes": obtener_texto(
            page, '[data-e2e="likes-count"]'
        ),
        "bio": obtener_texto(
            page, '[data-e2e="user-bio"]'
        ),
        "url": page.url,
    }

    return perfil


def main():
    print("=== MEDIA SCRAPER ===")

    entrada = input("Ingrese el username de TikTok: ")

    try:
        username = validar_username(entrada)
    except ValueError as error:
        print(f"Error: {error}")
        return

    url = f"https://www.tiktok.com/@{username}"

    print(f"\nPerfil solicitado: @{username}")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False
            )

            try:
                page = browser.new_page()

                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000
                )

                if response is None or response.status != 200:
                    print("No se obtuvo una respuesta HTTP 200.")
                    return

                print("Página recibida correctamente.")

                perfil = extraer_perfil(page, username)

                print("\n=== DATOS DEL PERFIL ===")
                print(
                    json.dumps(
                        perfil,
                        ensure_ascii=False,
                        indent=4
                    )
                )

                input(
                    "\nPresiona ENTER para cerrar Chromium..."
                )

            finally:
                browser.close()

    except Error as error:
        print(f"\nError de Playwright: {error}")

    except KeyboardInterrupt:
        print("\nEjecución interrumpida.")


if __name__ == "__main__":
    main()
