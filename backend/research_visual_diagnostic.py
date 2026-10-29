"""Explicit, observation-only TikTok search inspection. No repository or extractor."""
import asyncio
import logging
import time

from playwright.async_api import Error as PlaywrightError

from .reference_runtime import persistent_playwright
from .research_diagnostics import configure_logging, event, observe, safe_url, stage
from .research_tiktok_browser import resource_metadata, install_search_signals as install_visual_signals, navigate_search
from .vendor.scrapingtiktok.tiktok_scraper import TikTokScraper


async def snapshot(page, navigation):
    summary = await observe(page, navigation['http_status'])
    # Only booleans leave the page. No text, attributes or HTML are retained.
    surface = await page.evaluate('''() => {
        const visible = n => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden';
        const busy = [...document.querySelectorAll('[aria-busy="true"], [role="progressbar"], [data-e2e="search-loading"]')].some(visible);
        const text = !!document.body?.innerText.trim();
        const visual = [...document.querySelectorAll('img, video, canvas, svg, iframe')].some(visible);
        return {loading_indicator: busy, blank_surface: !text && !visual};
    }''')
    classification = summary['classification']
    if classification in ('authentication', 'captcha_or_verification', 'http_access_restricted'):
        state = 'access_restricted'
    elif classification == 'http_load_error':
        state = 'load_error'
    elif summary['candidate_video_links'] or (summary['search_json_items'] or 0) > 0:
        state = 'recognized_results'
    elif classification == 'recognized_empty_results':
        state = 'recognized_empty_results'
    elif summary['ready_state'] != 'complete' or surface['loading_indicator']:
        state = 'content_pending'
    elif time.monotonic() - navigation['started'] < 30:
        state = 'content_pending'
    elif surface['blank_surface']:
        state = 'blank_page'
    else:
        state = 'unrecognized_content'
    return {**summary, **surface, 'visual_state': state}


async def inspect_search(topic):
    engine = TikTokScraper(headless=False)
    async with persistent_playwright(engine) as playwright:
        with stage('visual_chromium_open'):
            await engine._setup_context(playwright)
        # Inspect the real page directly; perform no extraction, scroll or access-gate action.
        context = engine._shared_context
        page = await context.new_page()
        navigation = {'http_status': None, 'started': time.monotonic()}
        install_visual_signals(page, navigation)
        event('visual_navigation_started', url='https://www.tiktok.com/search', query='[omitida]')
        try:
            with stage('visual_search_navigation'):
                await navigate_search(page, topic)
        except PlaywrightError as error:
            event('visual_navigation_failed', level=logging.ERROR, error=error, url=safe_url(page.url))
            # Keep the window open even after navigation timeout to inspect late rendering.
        previous, last_report = None, 0
        while not page.is_closed():
            try:
                current = await snapshot(page, navigation)
                now = time.monotonic()
                if current != previous or now - last_report >= 10:
                    event('visual_page_state', **current)
                    previous, last_report = current, now
            except PlaywrightError as error:
                if page.is_closed():
                    break
                event('visual_inspection_pending', level=logging.WARNING, error=error,
                      url=safe_url(page.url))
            await asyncio.sleep(2)


def run_visual_diagnostic(topic):
    configure_logging()
    print('Diagnóstico visual local: una búsqueda, sin extracción ni MongoDB.', flush=True)
    print('La URL completa se ve en Chromium; la terminal omite query y datos privados. '
          'Los errores omiten mensajes y URLs de recursos.', flush=True)
    print('Observa la ventana real. Ante login/CAPTCHA, inspecciona y detén el diagnóstico; '
          'no se automatiza ninguna acción. Cierra la pestaña o pulsa Ctrl+C para terminar.', flush=True)
    try:
        asyncio.run(inspect_search(topic))
    except PlaywrightError as error:
        event('visual_browser_failed', level=logging.ERROR, error=error)
        raise SystemExit('No se pudo mantener Chromium visible. Revisa el log local y la sesión gráfica.') from None
    finally:
        event('visual_diagnostic_finished')
