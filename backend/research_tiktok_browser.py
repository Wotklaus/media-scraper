"""Shared browser navigation and safe load signals for thematic TikTok only."""
import hashlib
import logging
import os
import re
import time
from urllib.parse import quote, urlsplit

from .research_diagnostics import event, install_signals, safe_url

SEARCH_WAIT_UNTIL = 'domcontentloaded'


def browser_headless():
    # Visible mode is explicit. No stealth flags, fallback or access-gate handling.
    return os.getenv('MEDIA_SCRAPER_TIKTOK_HEADLESS', '1') != '0'


def search_url(topic):
    return 'https://www.tiktok.com/search?q=' + quote(topic, safe='')


async def navigate_search(page, topic, timeout_ms=30000):
    return await page.goto(search_url(topic), wait_until=SEARCH_WAIT_UNTIL, timeout=timeout_ms)


def resource_metadata(request):
    """Correlate a resource without retaining its URL, query or user-controlled path."""
    parsed = urlsplit(request.url)
    host = parsed.hostname or ''
    family = next((domain for domain in ('tiktok.com', 'tiktokcdn.com', 'tiktokcdn-us.com',
        'tiktokv.com', 'byteoversea.com', 'ibytedtos.com')
        if host == domain or host.endswith('.' + domain)), 'other')
    kind = request.resource_type
    return {'resource_type': kind if kind in ('document', 'script', 'stylesheet', 'image',
        'font', 'xhr', 'fetch', 'media', 'websocket') else 'other',
        'host_family': family,
        'resource_ref': hashlib.sha256((host + parsed.path).encode()).hexdigest()[:12]}


def install_search_signals(page, navigation, *, prefix='visual'):
    page = getattr(page, 'raw', page)
    install_signals(page)

    def failed(request):
        failure = request.failure or ''
        # Chromium's fixed error identifiers only, never arbitrary failure messages.
        reason = failure if re.fullmatch(r'net::ERR_[A-Z_]{1,80}', failure) else 'request_failed'
        event(prefix + '_request_failed', level=logging.WARNING, reason=reason, **resource_metadata(request))

    def javascript(error):
        allowed = ('EvalError', 'RangeError', 'ReferenceError', 'SyntaxError', 'TypeError', 'URIError', 'Error')
        match = re.match(r'^(EvalError|RangeError|ReferenceError|SyntaxError|TypeError|URIError|Error)(?=:|$)', str(error))
        name = getattr(error, 'name', None)
        event(prefix + '_javascript_error', level=logging.WARNING,
              error_type=name if name in allowed else match.group(1) if match else 'JavaScriptError')

    def response_seen(response):
        request = response.request
        if request.resource_type == 'document' and response.frame == page.main_frame:
            navigation['http_status'] = response.status
            event(prefix + '_main_response', url=safe_url(response.url), http_status=response.status)
        elif response.status >= 400:
            event(prefix + '_http_error', level=logging.WARNING, http_status=response.status,
                  **resource_metadata(request))

    def navigated(frame):
        if frame == page.main_frame:
            # The response event precedes the commit; keep its status for this URL.
            event(prefix + '_navigation_committed', url=safe_url(frame.url))

    def requested(request):
        if request.is_navigation_request() and request.frame == page.main_frame:
            navigation.update(http_status=None, started=time.monotonic())
            event(prefix + '_navigation_requested', url=safe_url(request.url))

    page.on('request', requested)
    page.on('requestfailed', failed)
    page.on('pageerror', javascript)
    page.on('response', response_seen)
    page.on('framenavigated', navigated)
    page.on('domcontentloaded', lambda: event(prefix + '_dom_loaded', url=safe_url(page.url)))
    page.on('load', lambda: event(prefix + '_load_event', url=safe_url(page.url)))
    page.on('console', lambda message: event(prefix + '_console_error', level=logging.WARNING)
            if message.type == 'error' else None)


