"""Actual local HTTP/UI integration, isolated transactional database and worker."""
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from backend import research_routes
from backend.research_repository import ResearchRepository
from backend.research_worker import ResearchWorker
from research_fake import Database
from test_results import live_server


class ResearchBrowserTests(unittest.TestCase):
    def test_create_controls_progress_records_and_navigation_at_three_widths(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (375, 768, 1280):
                    with self.subTest(width=width):
                        db = Database()
                        repo = ResearchRepository(db)
                        with patch.object(research_routes, 'get_database', return_value=db), live_server() as origin:
                            page = browser.new_page(viewport={'width': width, 'height': 1000})
                            page.set_default_timeout(8000)
                            errors = []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
                            page.goto(origin)
                            page.locator('[data-section="research"]').click()
                            page.wait_for_function("document.getElementById('researchStatus').textContent.includes('No hay investigaciones')")
                            self.assertIn('No reales', page.locator('#researchSourceLabel').inner_text())
                            page.locator('#researchTopic').fill('<script>自由研究 Ω</script>')
                            page.locator('#researchTarget').fill('30')
                            page.locator('#researchCreate').click()
                            page.wait_for_function("!document.getElementById('researchDetail').hidden")
                            self.assertIn('自由研究', page.locator('#researchHeading').inner_text())
                            self.assertEqual(page.locator('#researchDetail script').count(), 0)
                            self.assertFalse(ResearchWorker(repo).tick())
                            page.locator('[data-research-action="start"]').click()
                            page.wait_for_function("document.getElementById('researchState').textContent.includes('En cola')")
                            page.locator('[data-research-action="pause"]').click()
                            page.wait_for_function("document.getElementById('researchState').textContent === 'Pausada'")
                            self.assertFalse(ResearchWorker(repo).tick())
                            page.locator('[data-research-action="resume"]').click()
                            page.wait_for_function("document.getElementById('researchState').textContent.includes('En cola')")
                            worker = ResearchWorker(repo)
                            worker.tick(); worker.tick()
                            page.wait_for_function("document.getElementById('researchState').textContent === 'Objetivo alcanzado'")
                            page.wait_for_function("document.querySelectorAll('#researchRows tr').length === 25")
                            self.assertIn('30 / 30', page.locator('#researchProgressText').inner_text())
                            self.assertEqual(page.locator('#researchRows tr').count(), 25)
                            self.assertNotIn('prueba@example.invalid', page.locator('#researchRows').inner_text())
                            page.locator('#researchRecordsNext').click()
                            page.wait_for_function("document.querySelectorAll('#researchRows tr').length === 5")
                            self.assertTrue(page.locator('[data-research-action="resume"]').is_disabled())
                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                            page.locator('[data-section="general"]').click()
                            self.assertTrue(page.locator('#general').is_visible())
                            self.assertEqual(page.locator('.app-section:visible').count(), 1)
                            self.assertEqual(errors, [])
                            page.close()
            finally:
                browser.close()


    def test_youtube_source_controls_and_real_provenance_without_external_requests(self):
        from test_research_youtube import Transport
        from backend.research_youtube import YouTubeConnector
        with patch.dict('os.environ', {'YOUTUBE_API_KEY': 'TEST-NEVER-SENT'}), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                db = Database(); repo = ResearchRepository(db)
                with patch.object(research_routes, 'get_database', return_value=db), live_server() as origin:
                    page = browser.new_page(viewport={'width': 390, 'height': 1000})
                    page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
                    page.goto(origin); page.locator('[data-section="research"]').click()
                    page.wait_for_function("document.querySelectorAll('#researchSource option').length === 3")
                    self.assertFalse(page.locator('#researchSource option[value="tiktok"]').evaluate('(option) => option.disabled'))
                    page.select_option('#researchSource', 'youtube')
                    self.assertTrue(page.locator('#researchYouTubeConfig').is_visible())
                    self.assertTrue(page.locator('#researchSyntheticConfig').is_hidden())
                    page.fill('#researchTopic', 'Investigación sin categorías')
                    page.fill('#researchTarget', '10'); page.click('#researchCreate')
                    page.wait_for_function("!document.getElementById('researchDetail').hidden")
                    page.click('[data-research-action="start"]')
                    page.wait_for_function("document.getElementById('researchState').textContent.includes('En cola')")
                    worker = ResearchWorker(repo, YouTubeConnector(Transport()))
                    worker.tick(); worker.tick()
                    page.wait_for_function("document.getElementById('researchState').textContent === 'Objetivo alcanzado'")
                    self.assertIn('YouTube', page.locator('#researchStatus').inner_text())
                    self.assertNotIn('No reales', page.locator('#researchStatus').inner_text())
                    self.assertNotIn('persona@example.invalid', page.locator('#researchRows').inner_text())
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                    page.close()
            finally:
                browser.close()


    def test_tiktok_selection_without_permission_and_paused_restriction(self):
        from backend.research_sources import SourceFailure
        class Restricted:
            def read(self, **kwargs): raise SourceFailure('access_restricted', False)
        with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED': ''}), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                db = Database(); repo = ResearchRepository(db)
                with patch.object(research_routes, 'get_database', return_value=db), live_server() as origin:
                    page = browser.new_page(viewport={'width': 390, 'height': 1000})
                    page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
                    page.goto(origin); page.locator('[data-section="research"]').click()
                    page.wait_for_function("document.querySelectorAll('#researchSource option').length === 3")
                    page.select_option('#researchSource', 'tiktok')
                    self.assertTrue(page.locator('#researchTikTokConfig').is_visible())
                    self.assertTrue(page.locator('#researchSyntheticConfig').is_hidden())
                    self.assertTrue(page.locator('#researchYouTubeConfig').is_hidden())
                    page.fill('#researchTopic', 'Investigación temática libre')
                    page.fill('#researchTarget', '600'); page.click('#researchCreate')
                    page.wait_for_function("!document.getElementById('researchDetail').hidden")
                    self.assertIn('TikTok', page.locator('#researchStatus').inner_text())
                    self.assertNotIn('No reales', page.locator('#researchStatus').inner_text())
                    page.click('[data-research-action="start"]')
                    page.wait_for_function("document.getElementById('researchState').textContent.includes('En cola')")
                    ResearchWorker(repo, Restricted()).tick()
                    page.wait_for_function("document.getElementById('researchState').textContent === 'Pausada'")
                    self.assertIn('access_restricted', page.locator('#researchActivity').inner_text())
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                    page.close()
            finally:
                browser.close()
