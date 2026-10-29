"""Only controlled pages and isolated log files, never external acquisition."""
import asyncio
import io
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

from playwright.async_api import async_playwright

from backend import research_diagnostics as diagnostics
from backend.research_tiktok import TikTokConnector
from backend.research_sources import SourceFailure
from backend.reference_runtime import SharedBrowser, AccessRestricted
from backend.research_worker import ResearchWorker
from backend.research_repository import ResearchRepository
from backend.research_models import StudyCreate
from research_fake import Database


class DiagnosticLoggingTests(unittest.TestCase):
    def test_failed_dom_inspection_preserves_safe_navigation_evidence(self):
        from types import SimpleNamespace
        page = SimpleNamespace(url='https://www.tiktok.com/search?q=SECRET',
                               evaluate=AsyncMock(side_effect=RuntimeError('SECRET token')))
        with self.assertLogs(diagnostics.LOGGER, level='WARNING') as captured:
            self.assertIsNone(asyncio.run(diagnostics.diagnose(page, 'source_structure_changed', 503)))
        record = captured.records[0].event
        self.assertEqual(record['classification'], 'inspection_unavailable')
        self.assertEqual(record['http_status'], 503)
        self.assertEqual(record['url'], 'https://www.tiktok.com/search')
        self.assertTrue(record['traceback'])
        self.assertNotIn('SECRET', json.dumps(record))

    def test_json_log_local_traceback_without_exception_message_or_source_line(self):
        with tempfile.TemporaryDirectory() as root, patch.object(diagnostics, 'ROOT', Path(root)), patch.dict('os.environ', {'MEDIA_SCRAPER_RESEARCH_LOG_LEVEL': 'DEBUG'}), patch('sys.stderr', new_callable=io.StringIO) as terminal:
            try:
                diagnostics.configure_logging()
                try:
                    with diagnostics.stage('controlled'):
                        raise RuntimeError('SECRET cookies=private person@example.invalid https://x.invalid/?token=private')
                except RuntimeError:
                    pass
                output = (Path(root)/'worker.jsonl').read_text()
                self.assertNotIn('SECRET', output); self.assertNotIn('person@example.invalid', output)
                events = [json.loads(line) for line in output.splitlines()]
                self.assertEqual([e['event'] for e in events], ['stage_started', 'stage_failed'])
                self.assertTrue(events[1]['traceback']); self.assertEqual(events[1]['exception_type'], 'RuntimeError')
                self.assertIn('elapsed_seconds', events[1]); self.assertIn('stage_failed', terminal.getvalue())
                self.assertEqual((Path(root)/'worker.jsonl').stat().st_mode & 0o777, 0o600)
                with patch.dict('os.environ', {'MEDIA_SCRAPER_RESEARCH_LOG_LEVEL': 'OFF'}):
                    diagnostics.configure_logging(); diagnostics.event('must_not_appear')
                self.assertNotIn('must_not_appear', (Path(root)/'worker.jsonl').read_text())
            finally:
                for handler in diagnostics.LOGGER.handlers[:]:
                    diagnostics.LOGGER.removeHandler(handler); handler.close()
                diagnostics.LOGGER.addHandler(logging.NullHandler()); diagnostics.LOGGER.setLevel(logging.NOTSET)

    def test_safe_urls_strip_userinfo_queries_tokens_and_unknown_paths(self):
        for value in ('https://www.tiktok.com/search?q=PERSON&token=SECRET',
                      'https://u:SECRET@www.tiktok.com/@person/video/123?token=SECRET',
                      'https://www.tiktok.com/SECRET', 'https://SECRET.invalid/path'):
            safe = diagnostics.safe_url(value)
            self.assertNotIn('SECRET', safe); self.assertNotIn('PERSON', safe); self.assertNotIn('@person', safe)

    def test_worker_public_errors_stay_safe_with_local_traceback(self):
        repository = ResearchRepository(Database())
        identity = repository.create(StudyCreate(topic='private topic'))['study_id']
        repository.control(identity, 'start')
        class Broken:
            def read(self, **kwargs): raise RuntimeError('SECRET credentials')
        with self.assertLogs(diagnostics.LOGGER, level='INFO') as captured:
            ResearchWorker(repository, Broken()).tick()
        events = [record.event for record in captured.records]
        error = next(e for e in events if e['event'] == 'worker_processing_failed')
        self.assertTrue(error['traceback']); self.assertEqual(error['study_id'], identity)
        self.assertNotIn('SECRET', json.dumps(events)); self.assertNotIn('private topic', json.dumps(events))
        self.assertEqual(repository.detail(identity)['last_error'], 'processing_failed')


class DiagnosticBrowserTests(unittest.TestCase):
    def test_page_classification_metadata_debug_files_and_disabled_capture(self):
        async def scenario():
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    context = await browser.new_context()
                    await context.route('**/*', lambda route: route.fulfill(content_type='text/html', body='<title>SECRET person@example.invalid</title><main><p>PRIVATE COMMENT @person</p></main>'))
                    page = await context.new_page(); diagnostics.install_signals(page); await page.goto('https://www.tiktok.com/search?q=PRIVATE&token=SECRET')
                    with tempfile.TemporaryDirectory() as root, patch.object(diagnostics, 'ROOT', Path(root)):
                        with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_DEBUG': ''}), self.assertLogs(diagnostics.LOGGER, level='INFO') as captured:
                            summary = await diagnostics.diagnose(page, 'source_structure_changed', 200)
                        self.assertEqual(summary['classification'], 'search_structure_unknown')
                        self.assertEqual(list(Path(root).iterdir()), [])
                        self.assertNotIn('PRIVATE', json.dumps([r.event for r in captured.records]))
                        with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_DEBUG': '1'}):
                            await diagnostics.diagnose(page, 'source_structure_changed', 200)
                        self.assertEqual(len(list(Path(root).glob('*.json'))), 1)
                        self.assertEqual(len(list(Path(root).glob('*.png'))), 1)
                        for file in Path(root).glob('*.json'):
                            text = file.read_text(); self.assertNotIn('PRIVATE', text); self.assertNotIn('SECRET', text)
                            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
                    await page.evaluate("() => console.error('PRIVATE SECRET')")
                    await page.wait_for_timeout(20)
                    self.assertGreaterEqual((await diagnostics.observe(page, 200))['browser_errors']['console_errors'], 1)
                    for html, status, expected in (
                        ('<div id="captcha-test">PRIVATE</div>', 200, 'captcha_or_verification'),
                        ('<div data-e2e="login-modal">PRIVATE</div>', 200, 'authentication'),
                        ('<div data-e2e="search-empty">PRIVATE</div>', 200, 'recognized_empty_results'),
                        ('<main></main>', 403, 'http_access_restricted'),
                        ('<main></main>', 503, 'http_load_error'),
                        ('<main><a href="/about">About</a></main>', 200, 'search_structure_unknown'),
                        ('<main><a href="/@person/video/123">PRIVATE</a></main>', 200, 'search_results_markers')):
                        await page.set_content(html)
                        observation = await diagnostics.observe(page, status)
                        self.assertEqual(observation['classification'], expected)
                        if status >= 400:
                            self.assertTrue(observation['load_problem_suspected'])
                    await page.set_content('<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{"__DEFAULT_SCOPE__":{"webapp.search":{"itemList":[]}}}</script>')
                    summary = await diagnostics.observe(page, 200)
                    self.assertTrue(summary['json_present']); self.assertTrue(summary['item_list_present'])
                    self.assertEqual(summary['search_json_items'], 0)
                    self.assertEqual(summary['candidate_video_links'], 0)
                finally:
                    await browser.close()
        asyncio.run(scenario())

    def test_original_extraction_emits_navigation_comment_counts_and_timing(self):
        from test_research_tiktok import TikTokBrowserTests
        with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_DEBUG': ''}), self.assertLogs(diagnostics.LOGGER, level='INFO') as captured:
            TikTokBrowserTests().execute(kind='acquire')
        events = [r.event for r in captured.records]
        self.assertTrue(any(e['event'] == 'stage_finished' and e.get('stage') == 'chromium_open' and 'elapsed_seconds' in e for e in events))
        self.assertTrue(any(e['event'] == 'stage_finished' and e.get('stage') == 'publication_navigation' for e in events))
        self.assertTrue(any(e['event'] == 'comments_processed' and e['count'] == 1 for e in events))
        self.assertTrue(any(e['event'] == 'browser_diagnostic' and e['http_status'] == 200 for e in events))
        self.assertNotIn('Pregunta @lector', json.dumps(events))

    def test_unknown_structure_and_access_emit_diagnostics_before_page_closes(self):
        async def scenario():
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    for body, status, exception, classification in (
                        ('<main>Unknown PRIVATE</main>', 200, SourceFailure, 'search_structure_unknown'),
                        ('<main>Restricted PRIVATE</main>', 403, AccessRestricted, 'http_access_restricted'),
                        ('<div id="captcha-visible">PRIVATE</div>', 200, AccessRestricted, 'captcha_or_verification')):
                        context = await browser.new_context()
                        await context.route('**/*', lambda route: route.fulfill(status=status, content_type='text/html', body=body))
                        shared = SharedBrowser(context)
                        with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_DEBUG': ''}), self.assertLogs(diagnostics.LOGGER, level='INFO') as captured:
                            with self.assertRaises(exception):
                                await TikTokConnector().discover(await shared.new_context(), 'SECRET topic', 2, 1, timeout_seconds=0.6)
                        events = [r.event for r in captured.records]
                        observed = [e for e in events if e['event'] == 'browser_diagnostic']
                        self.assertTrue(observed); self.assertEqual(observed[-1]['classification'], classification)
                        self.assertEqual(observed[-1]['http_status'], status)
                        self.assertTrue(any(e['event'] == 'stage_failed' and e.get('traceback') for e in events))
                        self.assertTrue(all(p.is_closed() for p in context.pages))
                        self.assertNotIn('SECRET', json.dumps(events)); self.assertNotIn('PRIVATE', json.dumps(events))
                        await context.close()
                finally:
                    await browser.close()
        asyncio.run(scenario())
