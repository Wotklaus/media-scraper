"""UI contract only: local API fixtures, no provider, scraper or MongoDB."""
from pathlib import Path
import re
import unittest

from playwright.sync_api import sync_playwright

FRONTEND = Path(__file__).resolve().parent.parent / 'frontend'
STUDY = '233a3985-c2d3-4f1e-b67a-b5c0e37a1659'
AI_STUDY = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
EMPTY_STUDY = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


class ResearchAnalysisBrowserTests(unittest.TestCase):
    def test_switching_studies_keeps_results_separate_and_disables_empty_study(self):
        section = re.search(r'<section\b[^>]*\bid="research"[^>]*>.*?</section>',
                            (FRONTEND / 'index.html').read_text(), re.S).group()
        posts = []
        def respond(route):
            url = route.request.url
            study = next((identity for identity in (STUDY, AI_STUDY, EMPTY_STUDY) if identity in url), STUDY)
            count = {STUDY: 37, AI_STUDY: 75, EMPTY_STUDY: 0}[study]
            topic = {STUDY: 'cable utp', AI_STUDY: 'Inteligencia artificial', EMPTY_STUDY: 'Sin datos'}[study]
            if route.request.method == 'POST': posts.append(url)
            if url.endswith('/analysis'):
                if study == STUDY:
                    route.fulfill(json={'status': 'completed', 'eligible': True, 'comment_count': 37,
                        'embedding_model': 'guardado', 'model': 'guardado', 'generated_at': 'fecha', 'grouping': {'threshold': 0.58},
                        'result': {'comments': [], 'ambiguous_count': 0, 'category_counts': {}, 'groups': [],
                            'findings': [{'kind': 'theme', 'title': 'Solo cable UTP', 'count': 1, 'publication_count': 1, 'record_keys': []}],
                            'recommendations': []}})
                else:
                    route.fulfill(json={'status': 'unavailable', 'eligible': count > 0, 'comment_count': count,
                        'message': 'No hay comentarios preparados para analizar.' if not count else 'No hay análisis disponible.'})
            elif '/records?' in url:
                route.fulfill(json={'records': [], 'total': count, 'offset': 0, 'limit': 25})
            elif '/progress' in url:
                route.fulfill(json={'study_id': study, 'topic': topic, 'description': '', 'source': 'tiktok',
                    'synthetic': False, 'source_label': 'TikTok', 'status': 'exhausted', 'target_records': 100,
                    'progress_percent': count, 'counters': {'prepared': count, 'excluded': 0, 'duplicates': 0,
                        'received': count, 'publications_discovered': 1, 'publications_processed': 1,
                        'batches': 1, 'processing_seconds': 1}, 'pending_tasks': 0, 'failed_tasks': 0,
                    'updated_at': 'fecha', 'warnings': []})
            else:
                route.fulfill(content_type='text/html', body=section)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route('**/*', respond)
                page.goto('https://media-scraper.invalid/')
                page.add_script_tag(path=str(FRONTEND / 'research.js'))
                page.evaluate("document.getElementById('research').hidden=false")
                page.evaluate('id => window.research.select(id)', STUDY)
                self.assertIn('Solo cable UTP', page.locator('#researchAnalysisResults').text_content())
                page.evaluate('id => window.research.select(id)', AI_STUDY)
                self.assertEqual(page.locator('#researchHeading').text_content(), 'Inteligencia artificial')
                self.assertEqual(page.locator('#researchAnalyze').text_content(), 'Analizar 75 comentarios')
                self.assertTrue(page.locator('#researchAnalyze').is_enabled())
                self.assertNotIn('Solo cable UTP', page.locator('#researchAnalysisResults').text_content())
                page.evaluate('id => window.research.select(id)', EMPTY_STUDY)
                self.assertEqual(page.locator('#researchAnalyze').text_content(), 'Analizar 0 comentarios')
                self.assertTrue(page.locator('#researchAnalyze').is_disabled())
                self.assertIn('No hay comentarios', page.locator('#researchAnalysisStatus').text_content())
                self.assertEqual(posts, [])
            finally:
                browser.close()

    def test_on_demand_render_cached_read_processing_and_failure(self):
        section = re.search(r'<section\b[^>]*\bid="research"[^>]*>.*?</section>',
                            (FRONTEND / 'index.html').read_text(), re.S).group()
        comments = [{'record_key': str(i), 'publication_id': 'publication-fixture',
            'category': 'technical_question' if i < 2 else 'social_opinion', 'text': f'Comentario controlado {i}',
            'quote': 'Comentario', 'reason': 'Prueba de presentación', 'ambiguous': False, 'alternatives': []} for i in range(37)]
        completed = {'study_id': STUDY, 'status': 'completed', 'eligible': True, 'comment_count': 37, 'embedding_model': 'fixture-embedding',
            'model': 'fixture-analysis', 'generated_at': '2026-10-29', 'grouping': {'threshold': 0.72},
            'result': {'comments': comments, 'ambiguous_count': 0, 'category_counts': {'technical_question': 2, 'social_opinion': 35},
                'groups': [{'title': 'Grupo de prueba', 'count': 37, 'publication_count': 1, 'record_keys': [str(i) for i in range(37)]}],
                'findings': [{'kind': 'faq', 'title': 'Pregunta respaldada', 'count': 2, 'publication_count': 1, 'record_keys': ['0', '1']}],
                'recommendations': [{'activity': 'Actividad con respaldo de prueba', 'record_keys': ['0', '1']}]}}
        state = {'saved': {'status': 'unavailable', 'eligible': True, 'comment_count': 37}, 'posts': 0, 'fail_post': False}
        def respond(route):
            url = route.request.url
            if url.endswith('/analysis'):
                if route.request.method == 'POST':
                    state['posts'] += 1
                    if state['fail_post']:
                        route.fulfill(status=503, json={'detail': {'message': 'Proveedor no disponible; prueba controlada'}})
                        return
                    state['saved'] = completed
                route.fulfill(json=state['saved'])
            elif '/records?' in url:
                offset = int(url.split('offset=')[1].split('&')[0])
                route.fulfill(json={'records': [{'publication_id': 'fixture', 'text': f'Texto página {offset}', 'redactions': 0, 'synthetic': False}],
                    'total': 37, 'offset': offset, 'limit': 25})
            elif '/progress' in url:
                route.fulfill(json={'study_id': STUDY, 'topic': 'cable utp', 'description': '', 'source': 'tiktok',
                    'synthetic': False, 'source_label': 'TikTok · Playwright', 'status': 'exhausted', 'target_records': 400,
                    'progress_percent': 9.25, 'counters': {'prepared': 37, 'excluded': 0, 'duplicates': 0, 'received': 37,
                        'publications_discovered': 4, 'publications_processed': 4, 'batches': 5, 'processing_seconds': 1},
                    'pending_tasks': 0, 'failed_tasks': 0, 'updated_at': '2026-10-29', 'warnings': []})
            else:
                route.fulfill(content_type='text/html', body=section)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route('**/*', respond)
                page.goto('https://media-scraper.invalid/')
                page.add_script_tag(path=str(FRONTEND / 'research.js'))
                page.evaluate("document.getElementById('research').hidden=false")
                page.evaluate('id => window.research.select(id)', STUDY)
                self.assertEqual(state['posts'], 0)
                self.assertIn('No hay análisis', page.locator('#researchAnalysisStatus').text_content())
                self.assertEqual(page.locator('#researchAnalyze').text_content(), 'Analizar 37 comentarios')
                page.click('#researchExploreRecords')
                self.assertTrue(page.locator('#researchEvidenceDialog').evaluate('(dialog) => dialog.open'))
                self.assertIn('Texto página 0', page.locator('#researchDialogItems').text_content())
                page.locator('#researchDialogSearch').fill('sin coincidencia')
                self.assertIn('0 de 1', page.locator('#researchDialogCount').text_content())
                page.locator('#researchDialogSearch').fill('')
                page.click('#researchRecordsNext')
                page.wait_for_function("document.querySelector('#researchDialogItems').textContent.includes('Texto página 25')")
                page.click('#researchDialogClose')
                self.assertFalse(page.locator('#researchEvidenceDialog').evaluate('(dialog) => dialog.open'))
                page.click('#researchTabSemantic')
                page.click('#researchAnalyze')
                page.wait_for_function("document.querySelector('#researchAnalysisResults').textContent.includes('Resumen analítico')")
                text = page.locator('#researchAnalysisResults').text_content()
                for expected in ('37 comentarios', 'Dudas técnicas', 'Grupo de prueba', 'Pregunta respaldada',
                                 'Pendiente de revisión educativa'):
                    self.assertIn(expected, text)
                page.locator('#researchAnalysisResults').get_by_role('button', name='Ver 2 evidencias').first.click()
                self.assertIn('Comentario controlado 0', page.locator('#researchDialogItems').text_content())
                page.keyboard.press('Escape')
                self.assertFalse(page.locator('#researchEvidenceDialog').evaluate('(dialog) => dialog.open'))
                page.locator('#researchAnalysisResults').get_by_role('button', name='Ver 2 evidencias').first.click()
                page.mouse.click(2, 2)
                self.assertFalse(page.locator('#researchEvidenceDialog').evaluate('(dialog) => dialog.open'))
                page.locator('#researchTabSemantic').focus()
                page.keyboard.press('ArrowRight')
                self.assertEqual(page.locator('#researchTabStatistics').get_attribute('aria-selected'), 'true')
                page.click('#researchTabSemantic')
                self.assertTrue(page.locator('#researchAnalyze').is_disabled())
                page.click('#researchAnalysisRefresh')
                self.assertEqual(state['posts'], 1)
                state['saved'] = {'status': 'failed', 'eligible': True, 'comment_count': 37, 'failure': {'message': 'Fallo anterior de prueba'}}
                page.click('#researchAnalysisRefresh')
                page.wait_for_function("document.querySelector('#researchAnalysisStatus').textContent.includes('Fallo anterior')")
                state['fail_post'] = True
                page.click('#researchAnalyze')
                page.wait_for_function("document.querySelector('#researchAnalysisStatus').textContent.includes('Proveedor no disponible')")
                self.assertEqual(page.locator('#researchAnalysisResults').text_content(), '')
                self.assertTrue(page.locator('#researchAnalyze').is_enabled())
                state['saved'] = {'status': 'processing', 'eligible': True, 'comment_count': 37}
                page.click('#researchAnalysisRefresh')
                page.wait_for_function("document.querySelector('#researchAnalysisStatus').textContent.includes('en proceso')")
                self.assertTrue(page.locator('#researchAnalyze').is_disabled())
            finally:
                browser.close()
