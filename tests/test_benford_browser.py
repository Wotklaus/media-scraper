"""Offline Chromium integration: real UI and calculated fixture responses."""
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from backend.benford_repository import BenfordRepository
from backend.benford_routes import BenfordResponse
from test_benford import database

FRONTEND = Path(__file__).resolve().parent.parent / 'frontend'
ORIGIN = 'https://media-scraper.invalid'


class BenfordBrowserTests(unittest.TestCase):
    def test_navigation_chart_table_empty_errors_and_responsive_layout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (375, 768, 1280):
                    with self.subTest(width=width):
                        db, collections = database()
                        service = BenfordRepository(db)
                        calls, errors = [], []
                        state = {'error': False, 'no_profiles': False}
                        page = browser.new_page(viewport={'width': width, 'height': 950})
                        page.on('pageerror', lambda error: errors.append(str(error)))

                        def route_request(route):
                            parsed = urlparse(route.request.url)
                            if parsed.path.startswith('/api/'):
                                calls.append((route.request.method, parsed.path, parsed.query))
                                if state['error']:
                                    route.fulfill(status=503, json={'detail': 'No se pudieron consultar los datos para Benford.'})
                                elif parsed.path == '/api/stored-profiles':
                                    route.fulfill(json={'profiles': [] if state['no_profiles'] else [{'username': 'Example', 'nickname': '<script>prueba</script>'}]})
                                elif parsed.path == '/api/benford/Example':
                                    query = parse_qs(parsed.query)
                                    result = service.analyze('Example', query['metric'][0], query['dataset'][0])
                                    route.fulfill(json=BenfordResponse.model_validate(result).model_dump(mode='json'))
                                else:
                                    raise AssertionError('Unexpected API request: ' + route.request.url)
                            elif parsed.path == '/':
                                route.fulfill(path=str(FRONTEND / 'index.html'))
                            elif parsed.path[1:] in ('script.js', 'style.css', 'big-five.js', 'socialmind.js', 'benford.js'):
                                route.fulfill(path=str(FRONTEND / parsed.path[1:]))
                            else:
                                route.abort()

                        page.route('**/*', route_request)
                        page.goto(ORIGIN)
                        page.locator('[data-section="benford"]').click()
                        page.locator('#benfordProfile').select_option('Example')
                        self.assertEqual(len(calls), 1)  # opening/selection never analyzes
                        page.locator('#benfordAnalyze').click()
                        page.wait_for_function("!document.getElementById('benfordResults').hidden")
                        self.assertEqual(page.locator('#benford svg rect').count(), 18)
                        self.assertEqual(page.locator('#benford tbody tr').count(), 9)
                        self.assertIn('Muestra reducida', page.locator('#benfordResults').inner_text())
                        self.assertIn('no demuestra', page.locator('#benfordResults').inner_text())
                        self.assertEqual(page.locator('#benford script').count(), 0)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                        self.assertLessEqual(page.locator('#benford svg').bounding_box()['width'], width)
                        page.locator('#benfordDataset').select_option('history')
                        self.assertTrue(page.locator('#benfordResults').is_hidden())
                        page.locator('#benfordAnalyze').click()
                        page.wait_for_function("document.getElementById('benfordStatus').textContent.includes('Historial deduplicado')")
                        self.assertIn('Duplicados eliminados: 1', page.locator('#benfordResults').inner_text())
                        page.locator('#benfordMetric').select_option('saves')
                        page.locator('#benfordAnalyze').click()
                        page.wait_for_function("document.getElementById('benfordStatus').textContent.includes('Sin observaciones válidas')")
                        self.assertEqual(page.locator('#benford svg').count(), 0)
                        self.assertEqual(page.locator('#benford tbody tr').count(), 9)
                        state['error'] = True
                        page.locator('#benfordAnalyze').click()
                        page.wait_for_function("document.getElementById('benfordStatus').textContent.includes('No se pudieron')")
                        self.assertTrue(page.locator('#benfordResults').is_hidden())
                        state.update(error=False, no_profiles=True)
                        page.locator('#benfordRefresh').click()
                        page.wait_for_function("document.getElementById('benfordStatus').textContent.includes('No hay perfiles')")
                        self.assertTrue(page.locator('#benfordAnalyze').is_disabled())
                        page.locator('[data-section="general"]').click()
                        self.assertTrue(page.locator('#general').is_visible())
                        self.assertEqual(page.locator('.app-section:visible').count(), 1)
                        self.assertTrue(all(method == 'GET' for method, _, _ in calls))
                        self.assertEqual(errors, [])
                        page.close()
            finally:
                browser.close()
