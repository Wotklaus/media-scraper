"""Local JSON diagnostics: allowlisted metadata and message-free traceback frames."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from html import escape
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time
import traceback
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent / '.media-scraper' / 'diagnostics'
CONTEXT = ContextVar('research_diagnostic_context', default={})
LOGGER = logging.getLogger('media_scraper.research')
LOGGER.propagate = False
LOGGER.addHandler(logging.NullHandler())


def directory():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    ROOT.chmod(0o700)
    return ROOT


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'time': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname, **record.event}, ensure_ascii=False)


def configure_logging():
    for handler in LOGGER.handlers[:]:
        LOGGER.removeHandler(handler); handler.close()
    level = os.getenv('MEDIA_SCRAPER_RESEARCH_LOG_LEVEL', 'INFO').upper()
    if level == 'OFF':
        LOGGER.addHandler(logging.NullHandler()); LOGGER.setLevel(logging.CRITICAL + 1)
        return
    LOGGER.setLevel({'DEBUG': logging.DEBUG, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}.get(level, logging.INFO))
    stream = logging.StreamHandler(); stream.setFormatter(JsonFormatter()); LOGGER.addHandler(stream)
    path = directory() / 'worker.jsonl'
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600); os.close(fd)
    path.chmod(0o600)
    file = PrivateRotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    file.setFormatter(JsonFormatter()); LOGGER.addHandler(file)


def event(name, *, level=logging.INFO, error=None, **fields):
    data = {'event': name, **CONTEXT.get(), **fields}
    if error is not None:
        # No str(error), source lines, locals or chained exception messages.
        data['exception_type'] = type(error).__name__
        data['traceback'] = [{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                             for frame in traceback.extract_tb(error.__traceback__)[-20:]]
    LOGGER.log(level, '', extra={'event': data})


@contextmanager
def stage(name, **fields):
    started = time.perf_counter(); event('stage_started', stage=name, **fields)
    try:
        yield
    except BaseException as error:
        event('stage_failed', level=logging.ERROR, stage=name,
              elapsed_seconds=round(time.perf_counter()-started, 4), error=error, **fields)
        raise
    else:
        event('stage_finished', stage=name, elapsed_seconds=round(time.perf_counter()-started, 4), **fields)


def safe_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.hostname not in ('tiktok.com', 'www.tiktok.com'):
            return '[origen omitido]'
        path = parsed.path.rstrip('/')
        if path not in ('/search', '/login', '/signup', '/verify', '/captcha', '/challenge'):
            path = '/@redactado/video/[id]' if '/video/' in path else '/[ruta omitida]'
        return 'https://' + parsed.hostname + path
    except ValueError:
        return '[URL omitida]'


SELECTORS = {
    'main': 'main', 'search_items': '[data-e2e="search-video-item"]',
    'search_cards': 'a[data-e2e="search-card-video"]', 'candidate_links': 'main a[href], [data-e2e="search-video-item"] a[href], a[data-e2e="search-card-video"]',
    'empty': '[data-e2e="search-empty"]',
    'captcha': '[id*="captcha"], [class*="captcha"], iframe[src*="captcha"], iframe[src*="verify"]',
    'login': '[data-e2e="login-modal"], [data-e2e="login-dialog"]',
    'comments': '[data-e2e="comment-list"], [data-e2e="comment-item"]',
}


def install_signals(page):
    raw = getattr(page, 'raw', page)
    if hasattr(raw, '_research_signals'):
        return
    counts = {'failed_requests': 0, 'failed_scripts': 0, 'javascript_errors': 0, 'console_errors': 0}
    raw._research_signals = counts
    def failed(request):
        counts['failed_requests'] += 1
        if request.resource_type == 'script':
            counts['failed_scripts'] += 1
    def javascript_error(error):
        counts['javascript_errors'] += 1
    def console(message):
        if message.type == 'error':
            counts['console_errors'] += 1
    raw.on('requestfailed', failed)
    raw.on('pageerror', javascript_error)
    raw.on('console', console)


async def observe(page, status=None):
    page = getattr(page, 'raw', page)  # Read-only inspection even when an access guard stopped navigation.
    result = {'url': safe_url(page.url), 'http_status': status,
              'browser_errors': dict(getattr(page, '_research_signals', {}))}
    # This JS returns counts/booleans only: no HTML, attributes, text or JSON bodies.
    summary = await page.evaluate(r'''(selectors) => {
        const counts = {}, visible = {};
        for (const [key, selector] of Object.entries(selectors)) {
            const nodes = [...document.querySelectorAll(selector)];
            counts[key] = Math.min(nodes.length, 10000);
            visible[key] = nodes.some(n => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden');
        }
        const videoLinks = [...document.querySelectorAll(selectors.candidate_links)].filter(node => {
            try {
                const url = new URL(node.href, location.href);
                return url.protocol === 'https:' && ['tiktok.com', 'www.tiktok.com'].includes(url.hostname)
                    && /^\/@[^/]+\/video\/\d+\/?$/.test(url.pathname);
            } catch (_) { return false; }
        }).length;
        let jsonPresent = false, jsonValid = false, scope = false, search = false, itemList = false, video = false;
        let itemCount = null;
        const script = document.querySelector('script#__UNIVERSAL_DATA_FOR_REHYDRATION__');
        jsonPresent = !!script;
        if (script && script.textContent.length < 2000000) {
            try {
                const data = JSON.parse(script.textContent); jsonValid = true;
                scope = !!data?.__DEFAULT_SCOPE__;
                search = !!data?.__DEFAULT_SCOPE__?.['webapp.search'];
                itemList = Array.isArray(data?.__DEFAULT_SCOPE__?.['webapp.search']?.itemList);
                if (itemList) itemCount = Math.min(data.__DEFAULT_SCOPE__['webapp.search'].itemList.length, 10000);
                video = !!data?.__DEFAULT_SCOPE__?.['webapp.video-detail']?.itemInfo?.itemStruct;
            } catch (_) {}
        }
        const loadingIndicator = [...document.querySelectorAll('[aria-busy="true"], [role="progressbar"], [data-e2e="search-loading"]')]
            .some(n => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden');
        return {ready_state: document.readyState, loading_indicator: loadingIndicator, selectors: counts, visible,
            candidate_video_links: Math.min(videoLinks, 10000), search_json_items: itemCount,
            json_present: jsonPresent, json_valid: jsonValid, scope_present: scope,
            search_json_present: search, item_list_present: itemList, video_json_present: video};
    }''', SELECTORS)
    title = await page.title()
    # Unknown titles can contain a topic, author or personal data; retain only known UI titles.
    result['title_length'] = len(title)
    result['title'] = title if title in ('TikTok', 'TikTok - Make Your Day', 'Log in | TikTok', 'Login | TikTok') else '[título omitido]'
    result.update(summary)
    path = urlsplit(page.url).path.lower()
    if summary['visible']['captcha'] or any('/'+gate in path for gate in ('captcha', 'verify', 'challenge')):
        classification = 'captcha_or_verification'
    elif summary['visible']['login'] or any('/'+gate in path for gate in ('login', 'signup')):
        classification = 'authentication'
    elif status in (401, 403, 429):
        classification = 'http_access_restricted'
    elif status and status >= 400:
        classification = 'http_load_error'
    elif summary['ready_state'] == 'loading':
        classification = 'document_loading'
    elif summary['visible']['empty']:
        classification = 'recognized_empty_results'
    elif path.rstrip('/') == '/search':
        classification = 'search_results_markers' if summary['candidate_video_links'] or summary['item_list_present'] else 'search_structure_unknown'
    elif summary['video_json_present']:
        classification = 'video_document'
    else:
        classification = 'unknown_document'
    result['classification'] = classification
    result['load_problem_suspected'] = bool(
        summary['ready_state'] != 'complete'
        or any(result['browser_errors'].values())
        or (status is not None and status >= 400))
    return result


async def diagnose(page, code, status=None):
    try:
        page = getattr(page, 'raw', page)
        summary = await observe(page, status)
        event('browser_diagnostic', code=code, **summary)
        if os.getenv('MEDIA_SCRAPER_TIKTOK_DEBUG') == '1':
            identity = uuid4().hex
            path = directory() / identity
            data = {'code': code, **summary}
            with path.with_suffix('.json').open('x', encoding='utf-8') as file:
                os.chmod(file.name, 0o600); json.dump(data, file, ensure_ascii=False, indent=2)
            # Screenshot of a separate, sanitized view; never of original account/comment content.
            preview = await page.context.new_page()
            try:
                await preview.set_content('<html><head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"></head><body><h1>Diagnóstico saneado de TikTok</h1><pre style="white-space:pre-wrap">'+escape(json.dumps(data, ensure_ascii=False, indent=2))+'</pre></body></html>')
                await preview.screenshot(path=str(path.with_suffix('.png')), full_page=True)
                path.with_suffix('.png').chmod(0o600)
            finally:
                await preview.close()
            event('diagnostic_saved', diagnostic_id=identity)
        return summary
    except Exception as error:
        # Navigation can destroy the execution context before DOM inspection.
        # Preserve the available evidence even when evaluate/title cannot run.
        event('diagnostic_failed', level=logging.WARNING, error=error,
              code=code, url=safe_url(getattr(page, 'url', '')),
              http_status=status, classification='inspection_unavailable')
        return None


class ObservedPage:
    """Research-only wrapper: original extraction implementation remains untouched."""
    def __init__(self, page, on_diagnostic=None):
        self.page, self.status = page, None
        self.on_diagnostic = on_diagnostic
        install_signals(page)
        raw = getattr(page, 'raw', page)
        def response_seen(response):
            if response.request.resource_type == 'document' and response.frame == raw.main_frame:
                self.status = response.status
        raw.on('response', response_seen)

    def __getattr__(self, key):
        return getattr(self.page, key)

    async def diagnostic(self, code):
        summary = await diagnose(self.page, code, self.status)
        if self.on_diagnostic and summary is not None:
            self.on_diagnostic(code, summary)

    async def goto(self, *args, **kwargs):
        with stage('publication_navigation'):
            try:
                response = await self.page.goto(*args, **kwargs)
                self.status = response.status if response else None
                await self.diagnostic('publication_document_loaded')
                return response
            except BaseException:
                await self.diagnostic('publication_navigation_failed')
                raise

    async def close(self):
        if not self.page.is_closed():
            await self.diagnostic('publication_before_close')
        await self.page.close()


class ObservedContext:
    def __init__(self, context, on_page=None, on_diagnostic=None):
        self.context = context
        self.on_page, self.on_diagnostic = on_page, on_diagnostic
        self.pages = []

    async def new_page(self):
        page = ObservedPage(await self.context.new_page(), self.on_diagnostic)
        self.pages.append(page)
        if self.on_page:
            self.on_page(getattr(page.page, 'raw', page.page))
        return page

    async def diagnose_open_pages(self, code):
        for page in self.pages:
            if not page.is_closed():
                await page.diagnostic(code)
