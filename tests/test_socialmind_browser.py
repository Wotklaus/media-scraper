"""Offline UI checks: fixtures never reach MongoDB or paid providers."""
import json
import unittest
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'
ORIGIN = 'https://media-scraper.invalid'


class SocialMindBrowserTests(unittest.TestCase):
    def test_responsive_navigation_and_read_only_states(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (1440, 1024, 390):
                    with self.subTest(width=width):
                        calls, errors = [], []
                        state = {'empty': False, 'offline': False}
                        page = browser.new_page(viewport={'width': width, 'height': 1000})
                        page.on('pageerror', lambda error: errors.append(str(error)))

                        def route_request(route):
                            path = urlparse(route.request.url).path
                            if path.startswith('/api/'):
                                calls.append((route.request.method, path))
                                if state['offline']:
                                    route.fulfill(status=503, json={'detail': 'MongoDB no disponible'})
                                    return
                                if path == '/api/stored-profiles':
                                    result = {'profiles': [] if state['empty'] else [{'username': 'alpha', 'nickname': 'Perfil de prueba'}, {'username': 'zero'}]}
                                elif path.endswith('/publications'):
                                    username = path.split('/')[3]
                                    result = {'username': username, 'profile_id': username, 'publications': [], 'related': [] if username == 'zero' else [{'first_publication_id': '1', 'second_publication_id': '2', 'similarity': .75}], 'summary': {'available': 0 if username == 'zero' else 3, 'generated': 0 if username == 'zero' else 2, 'pending': 0 if username == 'zero' else 1, 'empty': 0, 'generation_pending': 0}}
                                elif path.endswith('/map'):
                                    result = {'profile_id': 'alpha', 'points': [], 'related': [], 'explained_variance_ratio': [], 'rank': 0}
                                else:
                                    username = path.split('/')[3]
                                    result = {'profile_id': username, 'status': 'missing'}
                                    if username == 'alpha' and path.endswith('/analysis'):
                                        result = {'profile_id': username, 'status': 'current', 'analysis': {'model': 'stored', 'interpretation': {'partial': True, 'themes': [{'name': '<script>Cocina</script>', 'publication_ids': ['1', '2']}], 'communication_style': []}}}
                                route.fulfill(content_type='application/json', body=json.dumps(result))
                            elif path == '/':
                                route.fulfill(path=str(FRONTEND / 'index.html'))
                            elif path[1:] in ('script.js', 'big-five.js', 'socialmind.js', 'style.css'):
                                route.fulfill(path=str(FRONTEND / path[1:]))
                            else:
                                route.abort()

                        page.route('**/*', route_request)
                        page.goto(ORIGIN)
                        for section in ('statistics', 'big-five', 'socialmind', 'general', 'socialmind'):
                            page.locator(f'[data-section="{section}"]').click()
                            self.assertTrue(page.locator('#' + section).is_visible())
                            self.assertEqual(page.locator('.app-section:visible').count(), 1)
                        page.locator('#smProfile').select_option('alpha')
                        page.wait_for_function("document.querySelector('#smResults').textContent.includes('Recomendaciones propuestas')")
                        text = page.locator('#smResults').inner_text()
                        self.assertIn('parcial', text)
                        self.assertIn('Sustento:', text)
                        self.assertIn('0.7500', text)
                        self.assertIn('OCEAN no disponibles', text)
                        self.assertEqual(page.locator('#smResults script').count(), 0)
                        self.assertEqual(page.locator('#socialmind').bounding_box()['width'], page.locator('main').bounding_box()['width'])
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        page.screenshot(path=f'/tmp/socialmind-{width}.png', full_page=True)
                        page.locator('#smProfile').select_option('zero')
                        page.wait_for_function("document.querySelector('#smResults').textContent.includes('0 publicaciones disponibles')")
                        self.assertNotIn('Cocina', page.locator('#smResults').inner_text())
                        state['empty'] = True
                        page.locator('#smRefresh').click()
                        page.wait_for_function("document.querySelector('#smStatus').textContent.includes('No hay perfiles')")
                        self.assertTrue(page.locator('#smProfile').is_disabled())
                        self.assertEqual(page.locator('#smResults').inner_text(), '')
                        state['offline'] = True
                        page.locator('#smRefresh').click()
                        page.wait_for_function("document.querySelector('#smStatus').textContent.includes('MongoDB no disponible')")
                        page.reload()
                        page.locator('[data-section="socialmind"]').click()
                        page.wait_for_function("document.querySelector('#smStatus').textContent.includes('MongoDB no disponible')")
                        self.assertTrue(all(method == 'GET' for method, _ in calls), calls)
                        self.assertEqual(errors, [])
                        page.close()
            finally:
                browser.close()
