"""Visual diagnostic contracts, entirely mocked: no browser, network or database."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend import research_visual_diagnostic as visual
from backend import research_diagnostics as diagnostics
from playwright.async_api import TimeoutError as BrowserTimeout


class VisualDiagnosticTests(unittest.TestCase):
    def test_load_states_do_not_equate_empty_json_with_results(self):
        base = {'classification': 'search_results_markers', 'candidate_video_links': 0,
                'search_json_items': 0, 'ready_state': 'complete'}
        async def check():
            page = SimpleNamespace(evaluate=AsyncMock(return_value={'loading_indicator': False, 'blank_surface': True}))
            with patch.object(visual, 'observe', new_callable=AsyncMock) as observe, patch.object(visual.time, 'monotonic', return_value=100):
                for changes, age, expected in (
                    ({}, 10, 'content_pending'), ({}, 40, 'blank_page'),
                    ({'candidate_video_links': 1}, 10, 'recognized_results'),
                    ({'search_json_items': 1}, 40, 'recognized_results'),
                    ({'classification': 'recognized_empty_results'}, 40, 'recognized_empty_results'),
                    ({'classification': 'captcha_or_verification'}, 40, 'access_restricted'),
                    ({'classification': 'authentication'}, 40, 'access_restricted'),
                    ({'classification': 'http_load_error'}, 40, 'load_error'),
                    ({'ready_state': 'interactive'}, 40, 'content_pending')):
                    observe.return_value = {**base, **changes}
                    result = await visual.snapshot(page, {'http_status': 200, 'started': 100-age})
                    self.assertEqual(result['visual_state'], expected)
                page.evaluate.return_value = {'loading_indicator': False, 'blank_surface': False}
                observe.return_value = base
                self.assertEqual((await visual.snapshot(page, {'http_status': 200, 'started': 0}))['visual_state'], 'unrecognized_content')
                page.evaluate.return_value['loading_indicator'] = True
                self.assertEqual((await visual.snapshot(page, {'http_status': 200, 'started': 0}))['visual_state'], 'content_pending')
        asyncio.run(check())

    def test_browser_events_keep_only_safe_error_categories(self):
        callbacks = {}
        page = SimpleNamespace(on=lambda name, fn: callbacks.setdefault(name, []).append(fn),
                               main_frame=object(), url='https://www.tiktok.com/search?q=SECRET')
        navigation = {'http_status': 200, 'started': 0}
        visual.install_visual_signals(page, navigation)
        request = SimpleNamespace(url='https://private-person.tiktokcdn.com/SECRET.js?token=SECRET',
            failure='net::ERR_CONNECTION_RESET', resource_type='script', frame=page.main_frame,
            is_navigation_request=lambda: True)
        with self.assertLogs(diagnostics.LOGGER, level='INFO') as captured:
            for callback in callbacks['requestfailed']: callback(request)
            for callback in callbacks['pageerror']: callback(Exception('ReferenceError: SECRET person@example.invalid'))
            for callback in callbacks['console']: callback(SimpleNamespace(type='error', text='SECRET'))
            for callback in callbacks['request']: callback(request)
            for callback in callbacks['response']:
                callback(SimpleNamespace(request=request, status=503, frame=page.main_frame, url=request.url))
            request.failure = 'SECRET arbitrary failure message'
            for callback in callbacks['requestfailed']: callback(request)
        records = [record.event for record in captured.records]
        self.assertNotIn('SECRET', json.dumps(records))
        self.assertNotIn('private-person', json.dumps(records))
        self.assertTrue(any(r.get('reason') == 'net::ERR_CONNECTION_RESET' for r in records))
        self.assertTrue(any(r.get('error_type') == 'ReferenceError' for r in records))
        self.assertEqual(navigation['http_status'], None)
        self.assertEqual(page._research_signals['failed_scripts'], 2)

    def test_visible_single_search_stays_open_after_timeout_without_extraction(self):
        @asynccontextmanager
        async def runtime(engine):
            yield object()
        async def check():
            page = Mock(url='https://www.tiktok.com/search?q=SECRET')
            page.goto = AsyncMock(side_effect=BrowserTimeout('SECRET URL'))
            page.is_closed.side_effect = [False, True]
            context = SimpleNamespace(new_page=AsyncMock(return_value=page))
            engine = SimpleNamespace(_shared_context=context, _setup_context=AsyncMock())
            with patch.object(visual, 'TikTokScraper', return_value=engine) as constructor, \
                 patch.object(visual, 'persistent_playwright', runtime), \
                 patch.object(visual, 'snapshot', new_callable=AsyncMock, return_value={'visual_state': 'content_pending'}) as snapshot, \
                 patch.object(visual.asyncio, 'sleep', new_callable=AsyncMock), \
                 self.assertLogs(diagnostics.LOGGER, level='INFO') as captured:
                await visual.inspect_search('SECRET tema')
            constructor.assert_called_once_with(headless=False)
            page.goto.assert_awaited_once_with('https://www.tiktok.com/search?q=SECRET%20tema',
                wait_until='domcontentloaded', timeout=30000)
            snapshot.assert_awaited_once()
            self.assertNotIn('SECRET', json.dumps([r.event for r in captured.records]))
            page.mouse.wheel.assert_not_called()
            page.screenshot.assert_not_called()
        asyncio.run(check())
