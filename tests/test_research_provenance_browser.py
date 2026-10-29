"""UI provenance labels only; all API responses local, no worker or database."""
from pathlib import Path
import re
import unittest

from playwright.sync_api import sync_playwright

FRONTEND = Path(__file__).resolve().parent.parent / 'frontend'


class ResearchProvenanceBrowserTests(unittest.TestCase):
    def test_real_synthetic_mixed_unknown_and_study_switch(self):
        section = re.search(r'<section\b[^>]*\bid="research"[^>]*>.*?</section>',
                            (FRONTEND / 'index.html').read_text(), re.S).group()
        current = {}
        calls = []
        def respond(route):
            calls.append(route.request.method)
            path = route.request.url
            if '/api/research/' not in path:
                route.fulfill(content_type='text/html', body=section)
            elif '/records?' in path:
                route.fulfill(json={'records': current['records'], 'total': len(current['records']),
                                    'offset': 0, 'limit': 25})
            else:
                route.fulfill(json=current['study'])

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route('**/*', respond)
                page.goto('https://media-scraper.invalid/')
                page.add_script_tag(path=str(FRONTEND / 'research.js'))
                self.assertEqual(page.locator('#researchRecordsHeading').text_content(), 'Registros preparados')
                for identity, flags, study_flag, heading, publication in (
                    ('real', [False, False], False, 'Registros recopilados', 'Publicación'),
                    ('synthetic', [True, True], True, 'Registros sintéticos · Datos de prueba — No reales', 'Publicación sintética'),
                    ('mixed', [False, True], False, 'Registros preparados', 'Publicación'),
                    ('missing', [False, None], False, 'Registros preparados', 'Publicación'),
                    ('conflicting', [False], True, 'Registros preparados', 'Publicación'),
                    ('empty', [], False, 'Registros preparados', 'Publicación'),
                    ('real-again', [False], False, 'Registros recopilados', 'Publicación')):
                    with self.subTest(identity=identity):
                        rows = [{'publication_id': f'publication-{i}', 'text': f'Comentario conservado {i}',
                                 'redactions': i, **({'synthetic': flag} if flag is not None else {})}
                                for i, flag in enumerate(flags)]
                        current.update(records=rows, study={'study_id': identity, 'topic': 'Tema conservado',
                            'description': 'Descripción conservada', 'synthetic': study_flag, 'source': 'tiktok',
                            'source_label': 'TikTok · Playwright', 'status': 'exhausted', 'target_records': 400,
                            'progress_percent': 5, 'counters': {'prepared': 20, 'excluded': 0, 'duplicates': 0,
                                'received': 20, 'publications_discovered': 2, 'publications_processed': 2,
                                'batches': 3, 'processing_seconds': 1.0}, 'pending_tasks': 0, 'failed_tasks': 0,
                            'updated_at': '2026-10-29', 'warnings': []})
                        page.evaluate('identity => window.research.select(identity)', identity)
                        self.assertEqual(page.locator('#researchRecordsHeading').text_content(), heading)
                        self.assertEqual(page.locator('#researchPublicationHeader').text_content(), publication)
                        self.assertEqual(page.locator('#researchRows tr').count(), len(rows))
                        for i, row in enumerate(rows):
                            self.assertEqual(page.locator('#researchRows tr').nth(i).locator('td').all_text_contents(),
                                             [row['publication_id'], row['text'], str(row['redactions'])])
                        self.assertIn('20 / 400', page.locator('#researchProgressText').text_content())
                        self.assertEqual(page.locator('#researchDescriptionText').text_content(), 'Descripción conservada')
                self.assertTrue(all(method == 'GET' for method in calls))
            finally:
                browser.close()
