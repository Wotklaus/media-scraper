"""Manual session setup and authorized capture commands."""

import argparse
import logging

from .demo import save_capture
from .reference_engine import scrape_profile
from .session import configure_session


def main():
    parser = argparse.ArgumentParser(description="Media Scraper local tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("session", help="Configure login manually in visible Chromium")
    capture = commands.add_parser("capture", help="Save an authorized real query")
    capture.add_argument("username")
    capture.add_argument("--authorized", action="store_true", required=True,
                         help="Confirm authorization to query and store this public data")
    worker = commands.add_parser('research-worker', help='Process synthetic research batches independently of HTTP')
    worker.add_argument('--once', action='store_true', help='Process at most one pending batch and exit')
    worker.add_argument('--poll-seconds', type=float, default=1.0)
    args = parser.parse_args()
    if args.command == 'research-worker' and not 0.1 <= args.poll_seconds <= 60:
        parser.error('--poll-seconds must be between 0.1 and 60')
    try:
        if args.command == 'research-worker':
            from .research_worker import run_worker
            try:
                run_worker(once=args.once, poll_seconds=args.poll_seconds)
            except (KeyboardInterrupt, EOFError):
                raise SystemExit('Trabajador detenido; el progreso confirmado se conserva.') from None
            except Exception:
                raise SystemExit('No se pudo ejecutar el trabajador. Comprueba MongoDB y su soporte de transacciones.') from None
        elif args.command == "session":
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
