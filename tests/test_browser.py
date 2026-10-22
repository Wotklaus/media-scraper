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

    def test_dashboard_grid_navigation_statistics_and_errors(self):
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
                self.assertEqual(page.locator('#videosGrid .video-card').count(), 10)
                self.assertIn('Visualizaciones', page.locator('.video-metrics').first.inner_text())
                for width, columns in ((1200, 3), (768, 2), (375, 1)):
                    page.set_viewport_size({'width': width, 'height': 900})
                    self.assertEqual(page.locator('#videosGrid').evaluate("el => getComputedStyle(el).gridTemplateColumns.split(' ').length"), columns)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                page.set_viewport_size({'width': 1200, 'height': 900})
                page.locator('.stat-item[data-field="followers"]').click()
                self.assertEqual(page.locator('dialog').count(), 0)
                original = page.evaluate('JSON.stringify(currentProfile)')
                page.get_by_role('button', name='Estadísticas', exact=True).click()
                self.assertTrue(page.locator('#general').is_hidden())
                self.assertTrue(page.locator('#statistics').is_visible())
                self.assertEqual(page.locator('#rankingList li').count(), 10)
                page.locator('#rankingSort').select_option('interactions')
                self.assertEqual(page.locator('#rankingList li').count(), 10)
                self.assertTrue(page.locator('#dailyMessage').is_visible())
                self.assertTrue(page.locator('#hashtagMessage').is_visible())
                page.get_by_role('button', name='Big Five', exact=True).click()
                self.assertEqual(page.locator('#big-five .tag').all_text_contents(), ['Pendiente'] * 4)
                page.get_by_role('button', name='General', exact=True).click()
                self.assertEqual(page.evaluate('JSON.stringify(currentProfile)'), original)
                self.assertEqual(calls, ['mode=real'])
                self.assertEqual(page.locator('#videosGrid .video-card').count(), 10)
                page.locator('#searchButton').click()
                page.wait_for_function("!document.getElementById('searchButton').disabled")
                self.assertEqual(page.locator('#videosGrid .video-card').count(), 10)
                page.locator('#username').fill('missing')
                page.locator('#searchButton').click()
                page.wait_for_function("document.getElementById('statusMessage').textContent.includes('TikTok solicita verificación')")
                self.assertTrue(page.locator('#dashboard').is_hidden())
                self.assertEqual(calls, ['mode=real', 'mode=real', 'mode=real'])
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_partial_states_real_metrics_and_all_returned_posts(self):
        profile = sample_profile()
        profile['avatar_url'] = None
        profile['videos'] = profile['videos'][:3]
        profile['videos'][0].update(title='Primera #Viaje #Ecuador', views='1.2K', likes='10', comments='2', shares='3', saves='1', preview_url=ORIGIN + '/missing-cover')
        profile['videos'][1].update(title='Segunda #viaje', views='200', likes='100', comments='0', shares='0', saves='0', preview_url=None)
        profile['videos'][2].update(title='<img src=x onerror=alert(1)>', views=None, likes=None, preview_url=None)
        profile['_meta']['warnings'] = ['DETALLE_TECNICO_SELECTOR_DOM']
        calls = []
        errors = []

        def route_request(route):
            parsed = urlparse(route.request.url)
            if parsed.path.startswith('/api/profile/'):
                calls.append(parsed.path)
                route.fulfill(content_type='application/json', body=json.dumps(profile))
            elif parsed.path in ('/', '/script.js', '/style.css'):
                route.fulfill(path=str(FRONTEND / ('index.html' if parsed.path == '/' else parsed.path[1:])))
            else:
                route.abort()

        with sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1200, 'height': 900})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/*', route_request)
                page.goto(ORIGIN)
                page.get_by_role('button', name='Estadísticas', exact=True).click()
                self.assertIn('Analiza un perfil', page.locator('#rankingMessage').inner_text())
                page.get_by_role('button', name='General', exact=True).click()
                page.locator('#username').fill('test_only')
                page.locator('#searchButton').click()
                page.wait_for_function("!document.getElementById('searchButton').disabled")
                self.assertEqual(page.locator('#videosGrid .video-card').count(), 3)
                self.assertIn('3 publicaciones de hasta 10', page.locator('#statusMessage').inner_text())
                self.assertNotIn('DETALLE_TECNICO', page.locator('body').inner_text())
                self.assertEqual(page.evaluate('currentProfile._meta.warnings'), profile['_meta']['warnings'])
                self.assertIn('Vista previa no disponible', page.locator('.video-thumbnail').first.inner_text())
                self.assertEqual(page.locator('.original-link[href]').count(), 3)
                page.get_by_role('button', name='Estadísticas', exact=True).click()
                self.assertEqual(page.locator('#rankingList li span').all_text_contents(), ['Primera #Viaje #Ecuador', 'Segunda #viaje'])
                self.assertIn('#viaje · 2', page.locator('#hashtagList').inner_text())
                self.assertIn('2 publicaciones con las cuatro métricas', page.locator('#interactionSummary').inner_text())
                page.locator('#rankingSort').select_option('interactions')
                self.assertEqual(page.locator('#rankingList li span').first.inner_text(), 'Segunda #viaje')
                self.assertEqual(page.evaluate('metricNumber(null)'), None)
                self.assertEqual(page.evaluate('metricNumber("N/A")'), None)
                self.assertEqual(page.evaluate('metricNumber("1,234")'), None)
                self.assertEqual(page.evaluate('metricNumber("0")'), 0)
                page.get_by_role('button', name='Big Five', exact=True).click()
                page.get_by_role('button', name='General', exact=True).click()
                self.assertEqual(len(calls), 1)
                # Frontend must not silently truncate a larger backend response.
                profile['videos'] = [dict(profile['videos'][0], id=str(index)) for index in range(12)]
                page.locator('#searchButton').click()
                page.wait_for_function("!document.getElementById('searchButton').disabled")
                self.assertEqual(page.locator('#videosGrid .video-card').count(), 12)
                self.assertIn('datos parciales', page.locator('#statusMessage').inner_text())
                page.get_by_role('button', name='Estadísticas', exact=True).click()
                self.assertEqual(page.locator('#rankingList li').count(), 10)
                profile['videos'] = []
                page.get_by_role('button', name='General', exact=True).click()
                page.locator('#searchButton').click()
                page.wait_for_function("!document.getElementById('searchButton').disabled")
                self.assertTrue(page.locator('#videosMessage').is_visible())
                page.get_by_role('button', name='Estadísticas', exact=True).click()
                self.assertEqual(page.locator('#rankingList li').count(), 0)
                self.assertTrue(page.locator('#rankingMessage').is_visible())
                self.assertTrue(page.locator('#hashtagMessage').is_visible())
                self.assertEqual(errors, [])
                page.get_by_role('button', name='General', exact=True).click()
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
