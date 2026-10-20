"""Offline Chromium checks; all requests use local synthetic fixtures."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from backend import session
from playwright.sync_api import sync_playwright
from test_modes import sample_profile

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
ORIGIN = "https://media-scraper.invalid"


class OfflineBrowserTests(unittest.TestCase):
    def test_profile_persists_cookie_and_local_storage(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, 'PRIVATE_DIR', Path(folder) / 'private'):
            for first_visit in (True, False):
                with session.persistent_context() as context:
                    context.route('**/*', lambda route: route.fulfill(body='<html>Local test</html>', content_type='text/html'))
                    page = context.new_page()
                    page.goto(ORIGIN)
                    if first_visit:
                        context.add_cookies([{'name': 'synthetic_test', 'value': 'offline',
                                              'url': ORIGIN, 'expires': 4102444800}])
                        page.evaluate("localStorage.setItem('synthetic_test', 'offline')")
                    else:
                        self.assertEqual(page.evaluate("localStorage.getItem('synthetic_test')"), 'offline')
                        self.assertTrue(any(c['name'] == 'synthetic_test' and c['value'] == 'offline'
                                            for c in context.cookies()))

    def test_dashboard_real_queries_ten_videos_pagination_and_errors(self):
        calls = []
        errors = []
        def route_request(route):
            parsed = urlparse(route.request.url)
            if parsed.path.startswith('/api/profile/'):
                calls.append(parsed.query)
                if parsed.path.endswith('/missing'):
                    route.fulfill(status=502, content_type='application/json',
                                  body=json.dumps({'detail': 'TikTok solicita verificación.'}))
                    return
                profile = sample_profile()
                profile.pop('cookies')
                profile['avatar_url'] = None
                for video in profile['videos']:
                    video['preview_url'] = None
                profile['_meta'] = ({'mode': 'demo', 'captured_at': '2026-10-19T12:00:00+00:00', 'warnings': []}
                                    if parsed.query == 'mode=demo' else {'mode': 'real', 'warnings': []})
                route.fulfill(content_type='application/json', body=json.dumps(profile))
            elif parsed.path in ('/', '/script.js', '/style.css'):
                name = 'index.html' if parsed.path == '/' else parsed.path[1:]
                route.fulfill(path=str(FRONTEND / name))
            else:
                route.abort()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/*', route_request)
                page.goto(ORIGIN)
                page.locator('#username').fill('test_only')
                page.locator('#searchButton').click()
                page.wait_for_function("!document.getElementById('dashboard').classList.contains('hidden')")
                self.assertEqual(page.locator('#queryMode, #dataSource').count(), 0)
                self.assertEqual(page.locator('#statusMessage').inner_text(), '')
                self.assertEqual(page.locator('.pagination-label').inner_text(), 'Video 1 de 10')
                self.assertIn('Visualizaciones', page.locator('.video-metrics').inner_text())
                for _ in range(9):
                    page.get_by_role('button', name='Siguiente →').click()
                self.assertEqual(page.locator('.pagination-label').inner_text(), 'Video 10 de 10')
                self.assertTrue(page.get_by_role('button', name='Siguiente →').is_disabled())
                page.get_by_role('button', name='← Anterior').click()
                self.assertEqual(page.locator('.pagination-label').inner_text(), 'Video 9 de 10')
                page.locator('.stat-item[data-field="followers"]').click()
                self.assertTrue(page.locator('#detailsModal').is_visible())
                page.locator('#closeDetails').click()
                page.locator('#searchButton').click()
                page.wait_for_function("!document.getElementById('searchButton').disabled")
                self.assertEqual(page.locator('.pagination-label').inner_text(), 'Video 1 de 10')
                page.locator('#username').fill('missing')
                page.locator('#searchButton').click()
                page.wait_for_function("document.getElementById('statusMessage').textContent.includes('TikTok solicita verificación')")
                self.assertTrue(page.locator('#dashboard').is_hidden())
                self.assertEqual(calls, ['mode=real', 'mode=real', 'mode=real'])
                self.assertEqual(errors, [])
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
