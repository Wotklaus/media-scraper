"""Manual session setup and authorized capture commands."""

import argparse
import logging

from .demo import save_capture
from .scraper import scrape_profile
from .session import configure_session


def main():
    parser = argparse.ArgumentParser(description="Media Scraper local tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("session", help="Configure login manually in visible Chromium")
    capture = commands.add_parser("capture", help="Save an authorized real query")
    capture.add_argument("username")
    capture.add_argument("--authorized", action="store_true", required=True,
                         help="Confirm authorization to query and store this public data")
    args = parser.parse_args()
    try:
        if args.command == "session":
            configure_session()
            print("Sesión local guardada. TikTok puede solicitar autenticación de nuevo.")
        else:
            profile = scrape_profile(args.username)
            for warning in profile.get("_meta", {}).get("warnings", []):
                logging.getLogger(__name__).debug(warning)
            path = save_capture(profile)
            print(f"Captura guardada: {path.name}")
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from None
    except OSError:
        raise SystemExit("No se pudo acceder a los datos locales. Comprueba los permisos.") from None
    except (KeyboardInterrupt, EOFError):
        raise SystemExit("Operación cancelada; Chromium se ha cerrado.") from None


if __name__ == "__main__":
    main()
