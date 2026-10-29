"""Manual session setup and authorized capture commands."""

import argparse
import logging


def main():
    parser = argparse.ArgumentParser(description="Media Scraper local tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("session", help="Configure login manually in visible Chromium")
    visual = commands.add_parser('tiktok-visual-diagnostic', help='Observe one real search in visible Chromium, without extraction or MongoDB')
    visual.add_argument('--topic', help='Search topic; prompted locally when omitted')
    capture = commands.add_parser("capture", help="Save an authorized real query")
    capture.add_argument("username")
    capture.add_argument("--authorized", action="store_true", required=True,
                         help="Confirm authorization to query and store this public data")
    worker = commands.add_parser('research-worker', help='Process configured research sources independently of HTTP')
    worker.add_argument('--once', action='store_true', help='Process at most one pending batch and exit')
    worker.add_argument('--poll-seconds', type=float, default=1.0)
    args = parser.parse_args()
    if args.command == 'research-worker' and not 0.1 <= args.poll_seconds <= 60:
        parser.error('--poll-seconds must be between 0.1 and 60')
    try:
        if args.command == 'tiktok-visual-diagnostic':
            from .research_visual_diagnostic import run_visual_diagnostic
            topic = (args.topic if args.topic is not None else input('Tema de la búsqueda que falla: ')).strip()
            if not topic or len(topic) > 300:
                parser.error('El tema debe contener entre 1 y 300 caracteres')
            run_visual_diagnostic(topic)
        elif args.command == 'research-worker':
            from .research_worker import run_worker
            try:
                run_worker(once=args.once, poll_seconds=args.poll_seconds)
            except (KeyboardInterrupt, EOFError):
                raise SystemExit('Trabajador detenido; el progreso confirmado se conserva.') from None
            except Exception:
                raise SystemExit('No se pudo ejecutar el trabajador. Comprueba MongoDB y su soporte de transacciones.') from None
        elif args.command == "session":
            from .session import configure_session
            configure_session()
            print("Sesión local guardada. TikTok puede solicitar autenticación de nuevo.")
        else:
            from .demo import save_capture
            from .reference_engine import scrape_profile
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
