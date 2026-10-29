"""Targeted discovery regressions. Chromium responses are all intercepted locally."""
import asyncio
import json
import time
import unittest
from unittest.mock import patch, AsyncMock, Mock
from contextlib import asynccontextmanager
from types import SimpleNamespace

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from backend.reference_runtime import SharedBrowser, AccessRestricted
from backend.research_diagnostics import LOGGER
from backend.research_sources import SourceFailure
from backend.research_tiktok import TikTokConnector
from backend.research_models import StudyCreate
from backend.research_repository import ResearchRepository
from backend.research_worker import ResearchWorker
from research_fake import Database
from backend.research_tiktok_browser import navigate_search

URL = 'https://www.tiktok.com/@example/video/333'


class DeferredDiscoveryTests(unittest.TestCase):
    def run_page(self, html, *, timeout=1, wanted=2, abort_scripts=False, dom_timeout=False):
        async def scenario():
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    context = await browser.new_context()
                    async def respond(route):
                        if abort_scripts and route.request.resource_type == 'script':
                            await route.abort('failed')
                        else:
                            await route.fulfill(content_type='text/html', body=html)
                    await context.route('**/*', respond)
                    if dom_timeout:
                        def simulate_timeout(page):
                            original = page.goto
                            async def goto(*args, **kwargs):
                                kwargs['wait_until'] = 'commit'
                                await original(*args, **kwargs)
                                raise PlaywrightTimeout('Controlled DOMContentLoaded timeout')
                            page.goto = goto
                        context.on('page', simulate_timeout)
                    shared = SharedBrowser(context)
                    rows = await TikTokConnector().discover(await shared.new_context(), 'PRIVATE topic',
                        wanted, 0, timeout_seconds=timeout)
                    self.assertTrue(all(page.is_closed() for page in context.pages))
                    return rows
                finally:
                    await browser.close()
        with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_DEBUG': '0'}):
            return asyncio.run(scenario())

    def test_results_after_three_seconds_despite_empty_initial_json(self):
        html = '''<main></main><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
          {"__DEFAULT_SCOPE__":{"webapp.search":{"itemList":[]}}}</script>
          <script>setTimeout(() => {document.querySelector('main').innerHTML =
          '<a href="URL">video</a><a href="URL?tracking=1">duplicate</a>' +
          '<a href="https://evil.invalid/@example/video/9">foreign</a>';}, 3200)</script>'''.replace('URL', URL)
        with self.assertLogs(LOGGER, level='INFO') as captured:
            rows = self.run_page(html, timeout=6)
        self.assertEqual([row['publication_id'] for row in rows], [URL])
        events = [record.event for record in captured.records]
        first = next(event for event in events if event['event'] == 'first_search_result')
        self.assertGreaterEqual(first['elapsed_seconds'], 3)
        final = next(event for event in events if event['event'] == 'stage_finished' and event['stage'] == 'results_detection')
        self.assertEqual(final['valid_publications'], 1)
        self.assertNotIn('PRIVATE topic', json.dumps(events))

    def test_delayed_json_results_without_links(self):
        item = {'id': '333', 'author': {'uniqueId': 'example'}}
        payload = json.dumps({'__DEFAULT_SCOPE__': {'webapp.search': {'itemList': [item]}}})
        html = '<main></main><script>setTimeout(() => {const s=document.createElement("script"); s.id="__UNIVERSAL_DATA_FOR_REHYDRATION__"; s.type="application/json"; s.textContent=' + json.dumps(payload) + '; document.body.append(s);}, 400)</script>'
        self.assertEqual(self.run_page(html, timeout=2)[0]['publication_id'], URL)

    def test_explicit_empty_results_arrive_later(self):
        html = '<main></main><script>setTimeout(() => document.querySelector("main").innerHTML=\'<div data-e2e="search-empty">Empty</div>\', 400)</script>'
        self.assertEqual(self.run_page(html, timeout=2), [])

    def test_delayed_access_gate_stops_waiting(self):
        html = '<main></main><script>setTimeout(() => document.querySelector("main").innerHTML=\'<div id="captcha-visible">Stop</div>\', 400)</script>'
        started = time.monotonic()
        with self.assertRaises(AccessRestricted):
            self.run_page(html, timeout=5)
        self.assertLess(time.monotonic() - started, 4)

    def test_spinner_times_out_instead_of_structure_changed(self):
        with self.assertRaises(SourceFailure) as caught:
            self.run_page('<main aria-busy="true"></main>', timeout=0.8)
        self.assertEqual(caught.exception.code, 'source_load_timeout')
        self.assertTrue(caught.exception.retryable)

    def test_complete_unknown_document_waits_until_deadline(self):
        with self.assertLogs(LOGGER, level='INFO') as captured, self.assertRaises(SourceFailure) as caught:
            self.run_page('<main>Unknown structure</main>', timeout=0.8)
        self.assertEqual(caught.exception.code, 'source_structure_changed')
        detection = next(record.event for record in captured.records if record.event['event'] == 'stage_failed' and record.event['stage'] == 'results_detection')
        self.assertGreaterEqual(detection['elapsed_seconds'], 0.75)

    def test_dom_load_timeout_after_http_200_still_waits_for_results(self):
        html = '<main></main><script>setTimeout(()=>document.querySelector("main").innerHTML='+json.dumps('<a href="'+URL+'">Video</a>')+', 400)</script>'
        self.assertEqual(self.run_page(html, timeout=2, dom_timeout=True)[0]['publication_id'], URL)

    def test_worker_logs_safe_script_failure_and_js_error_not_access_restriction(self):
        html = '<main></main><script src="/broken-script?token=SECRET"></script><script>throw new ReferenceError("SECRET private text")</script>'
        with self.assertLogs(LOGGER, level='INFO') as logs, self.assertRaises(SourceFailure) as caught:
            self.run_page(html, timeout=0.8, abort_scripts=True)
        self.assertEqual(caught.exception.code, 'source_load_timeout')
        events = [record.event for record in logs.records]
        failed = next(e for e in events if e['event'] == 'search_request_failed')
        self.assertEqual(failed['resource_type'], 'script')
        self.assertEqual(failed['reason'], 'net::ERR_FAILED')
        self.assertTrue(any(e['event'] == 'search_javascript_error' and e['error_type'] == 'ReferenceError' for e in events))
        self.assertNotIn('SECRET', json.dumps(events))


class SearchBrowserParityTests(unittest.TestCase):
    def test_topic_is_one_encoded_query_parameter(self):
        from urllib.parse import parse_qs, urlsplit
        page = SimpleNamespace(goto=AsyncMock())
        topic = 'Inteligencia artificial & salud / ética'
        asyncio.run(navigate_search(page, topic))
        self.assertEqual(parse_qs(urlsplit(page.goto.call_args.args[0]).query), {'q': [topic]})
        self.assertEqual(page.goto.call_args.kwargs['wait_until'], 'domcontentloaded')

    def test_visible_mode_is_explicit_and_theme_only(self):
        @asynccontextmanager
        async def runtime(engine):
            yield object()
        engine = SimpleNamespace(_setup_context=AsyncMock(return_value=(None, object())))
        config = StudyCreate(topic='local', source='tiktok').source_config.model_dump()
        for setting, expected in (('0', False), ('1', True)):
            with self.subTest(setting=setting), patch.dict('os.environ', {
                'MEDIA_SCRAPER_TIKTOK_HEADLESS': setting, 'MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED': '1'}), \
                 patch('backend.research_tiktok.TikTokScraper', return_value=engine) as factory, \
                 patch('backend.research_tiktok.persistent_playwright', runtime), \
                 patch.object(TikTokConnector, 'discover', new_callable=AsyncMock, return_value=[]):
                asyncio.run(TikTokConnector().collect('local', config, 'discover', None, 1))
                factory.assert_called_once_with(headless=expected)


class DiscoveryTimeoutTests(unittest.TestCase):
    def test_worker_preserves_safe_load_timeout_code(self):
        class TimedOut:
            def read(self, **kwargs):
                raise SourceFailure('source_load_timeout', True)
        repo = ResearchRepository(Database())
        identity = repo.create(StudyCreate(topic='local', source='tiktok'))['study_id']
        repo.control(identity, 'start')
        ResearchWorker(repo, TimedOut()).tick()
        self.assertEqual(repo.detail(identity)['last_error'], 'source_load_timeout')

    def test_outer_discovery_deadline_is_not_browser_unavailable(self):
        async def slow(*args):
            await asyncio.sleep(1)
        config = StudyCreate(topic='local', source='tiktok').source_config.model_dump()
        config['batch_timeout_seconds'] = 0.01
        with patch.object(TikTokConnector, 'collect', side_effect=slow), self.assertRaises(SourceFailure) as caught:
            TikTokConnector().read(topic='local', config=config, kind='discover', publication_id=None,
                cursor=None, limit=2, attempt=1)
        self.assertEqual(caught.exception.code, 'source_load_timeout')
