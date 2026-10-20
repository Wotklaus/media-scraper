"""Terminal JSON and downloads with local synthetic responses only."""

import asyncio
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import uvicorn

from backend import main
from backend.presentation import print_profile
from test_modes import request, sample_profile


@contextmanager
def live_server():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(main.app, log_level='error', lifespan='off'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError('Local FastAPI fixture did not start')
                threading.Event().wait(0.01)
            yield f'http://127.0.0.1:{listener.getsockname()[1]}'
        finally:
            server.should_exit = True
            thread.join(timeout=5)


class TerminalTests(unittest.TestCase):
    def test_public_unicode_json_preserves_totals_missing_values_and_response(self):
        profile = sample_profile()
        profile.update(nickname='José, "你好" 🎵', bio='Primera línea\nSegunda línea', password='secret')
        profile['videos'][0].update(views=None, comments='500', saves='N/A', likes=0)
        profile['_meta'].update(warnings=['Datos parciales ñ'], credentials='secret')
        original = deepcopy(profile)
        output = io.StringIO()
        with redirect_stdout(output):
            print_profile(profile)
        data = json.loads(output.getvalue())
        self.assertEqual(data['followers'], '20')
        self.assertEqual(data['following'], '3')
        self.assertEqual(data['likes'], '100')
        self.assertEqual(data['nickname'], profile['nickname'])
        self.assertEqual(data['videos'][0]['comments'], '500')
        self.assertEqual(len(data['videos'][0]['comments_list']), 1)
        self.assertIsNone(data['videos'][0]['views'])
        self.assertEqual(data['videos'][0]['saves'], 'N/A')
        self.assertEqual(data['videos'][0]['likes'], 0)
        self.assertEqual(data['_meta']['warnings'], ['Datos parciales ñ'])
        self.assertIn('\n  "username"', output.getvalue())
        self.assertIn('José,', output.getvalue())
        self.assertIn('🎵', output.getvalue())
        self.assertNotIn('secret', output.getvalue())
        self.assertNotIn('cookies', output.getvalue())
        self.assertEqual(profile, original)

    def test_real_and_demo_api_responses_unchanged_and_each_prints_one_json(self):
        for mode in ('real', 'demo'):
            with self.subTest(mode=mode):
                profile = sample_profile()
                profile['_meta']['mode'] = mode
                output = io.StringIO()
                with patch.object(main, 'scrape_profile', return_value=profile) as scrape, patch.object(main, 'load_capture', return_value=profile) as load, redirect_stdout(output):
                    status, data = asyncio.run(request('/api/profile/test_only', f'mode={mode}'.encode()))
                self.assertEqual(status, 200)
                self.assertEqual(data, profile)
                self.assertEqual(json.loads(output.getvalue())['_meta']['mode'], mode)
                (load if mode == 'demo' else scrape).assert_called_once_with('test_only')
                (scrape if mode == 'demo' else load).assert_not_called()

    def test_failed_query_has_no_success_json(self):
        output = io.StringIO()
        with patch.object(main, 'scrape_profile', side_effect=RuntimeError('TikTok solicita verificación.')), redirect_stdout(output):
            status, data = asyncio.run(request('/api/profile/test_only'))
        self.assertEqual(status, 502)
        self.assertEqual(data['detail'], 'TikTok solicita verificación.')
        self.assertEqual(output.getvalue(), '')

    def test_empty_publications_and_url_credentials_are_safe(self):
        profile = sample_profile()
        profile.update(videos=[], avatar_url=None, followers=None,
                       url='https://user:password@www.tiktok.com/@test_only?token=secret#private')
        output = io.StringIO()
        with redirect_stdout(output):
            print_profile(profile)
        data = json.loads(output.getvalue())
        self.assertEqual(data['videos'], [])
        self.assertIsNone(data['followers'])
        self.assertIsNone(data['avatar_url'])
        self.assertEqual(data['url'], 'https://www.tiktok.com/@test_only')
        for text in ('password', 'secret', 'private'):
            self.assertNotIn(text, output.getvalue())


class DownloadTests(unittest.TestCase):
    def test_served_dashboard_downloads_current_query_without_extra_requests(self):
        profile = sample_profile()
        profile.update(nickname='José, "你好" 🎵', bio='Bio, "cita"\nlínea dos', avatar_url=None)
        for video in profile['videos']:
            video['preview_url'] = None
        profile['videos'][0].update(title='=HYPERLINK("formula")', comments='500', saves='N/A', views=None)
        profile['videos'][1]['title'] = 'Descripción, "cita"\nsalto 🎵'
        profile['videos'][1]['comments_list'][0]['text'] = 'Comentario, "cita"\nlínea dos'
        empty = deepcopy(profile)
        empty.update(username='empty_profile', videos=[], bio=None)
        calls = []
        errors = []
        def scrape(username):
            calls.append(username)
            if username == 'missing':
                raise RuntimeError('TikTok solicita verificación.')
            return empty if username == 'empty_profile' else profile
        with patch.object(main, 'scrape_profile', side_effect=scrape), patch.object(main, 'load_capture') as load, live_server() as origin, sync_playwright() as driver, tempfile.TemporaryDirectory() as folder:
            browser = driver.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1200, 'height': 900}, accept_downloads=True)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
                response = page.goto(origin)
                self.assertEqual(response.body(), (main.FRONTEND_DIR / 'index.html').read_bytes())
                for name in ('script.js', 'style.css'):
                    asset = page.request.get(origin + '/' + name)
                    self.assertEqual(asset.body(), (main.FRONTEND_DIR / name).read_bytes())
                self.assertEqual(page.locator('#queryMode, #dataSource').count(), 0)
                self.assertNotIn('Origen de los datos', page.locator('body').inner_text())
                self.assertTrue(page.locator('#downloadJSON').is_disabled())
                self.assertTrue(page.locator('#downloadCSV').is_disabled())
                for current in (profile, empty):
                    page.locator('#username').fill(current['username'])
                    page.get_by_role('button', name='Analizar', exact=True).click()
                    page.wait_for_function("!document.getElementById('searchButton').disabled")
                    self.assertEqual(page.locator('#statusMessage').inner_text(), '')
                    self.assertNotIn('CONSULTA REAL', page.locator('body').inner_text())
                    self.assertTrue(page.locator('#downloadJSON').is_enabled())
                    self.assertTrue(page.locator('#downloadCSV').is_enabled())
                    card = page.locator('.profile-card').bounding_box()
                    left = page.locator('#downloadJSON').bounding_box()
                    right = page.locator('#downloadCSV').bounding_box()
                    self.assertGreaterEqual(left['y'], card['y'] + card['height'])
                    self.assertAlmostEqual(left['y'], right['y'], delta=1)
                    self.assertGreaterEqual(left['x'], card['x'])
                    self.assertLessEqual(right['x'] + right['width'], card['x'] + card['width'])
                    if current['videos']:
                        right_column = page.locator('.right-column').bounding_box()
                        self.assertAlmostEqual(right_column['y'], card['y'], delta=1)
                        page.get_by_role('button', name='Siguiente →').click()
                        self.assertEqual(page.locator('.pagination-label').inner_text(), 'Video 2 de 10')
                    calls_before = len(calls)
                    for extension, label in [('json', 'Descargar JSON'), ('csv', 'Descargar CSV')]:
                        with page.expect_download() as event:
                            page.get_by_role('button', name=label, exact=True).click()
                        download = event.value
                        self.assertEqual(download.suggested_filename, f'media-scraper_{current["username"]}.{extension}')
                        path = Path(folder) / download.suggested_filename
                        download.save_as(path)
                        raw = path.read_bytes()
                        if extension == 'json':
                            data = json.loads(raw)
                            self.assertEqual(data['nickname'], current['nickname'])
                            self.assertEqual(data['bio'], current['bio'])
                            self.assertEqual(len(data['videos']), len(current['videos']))
                            self.assertEqual(data['followers_users'], current['followers_users'])
                            self.assertNotIn('cookies', data)
                            self.assertEqual(data['_meta'], current['_meta'])
                            if data['videos']:
                                self.assertEqual(data['videos'][0]['views'], None)
                                self.assertEqual(data['videos'][0]['comments'], '500')
                                self.assertNotIn('cookies', data['videos'][0]['comments_list'][0])
                        else:
                            self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
                            rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline='')))
                            self.assertEqual(len(rows), max(1, len(current['videos'])))
                            self.assertEqual(rows[0]['Usuario'], current['username'])
                            self.assertEqual(rows[0]['Nickname'], current['nickname'])
                            self.assertEqual(rows[0]['Seguidores'], '20')
                            if current['videos']:
                                self.assertTrue(rows[0]['Descripción'].startswith("'="))
                                self.assertEqual(rows[0]['Comentarios'], '500')
                                self.assertEqual(rows[0]['Visualizaciones'], 'null')
                                self.assertEqual(rows[0]['Guardados'], 'N/A')
                                self.assertEqual(rows[1]['Descripción'], current['videos'][1]['title'])
                                self.assertEqual(json.loads(rows[1]['Comentarios recuperados'])[0]['text'], current['videos'][1]['comments_list'][0]['text'])
                            else:
                                self.assertEqual(rows[0]['URL publicación'], 'null')
                                self.assertEqual(rows[0]['Biografía'], 'null')
                    self.assertEqual(len(calls), calls_before)
                    page.set_viewport_size({'width': 375, 'height': 812})
                    mobile_left = page.locator('#downloadJSON').bounding_box()
                    mobile_right = page.locator('#downloadCSV').bounding_box()
                    self.assertAlmostEqual(mobile_left['y'], mobile_right['y'], delta=1)
                    self.assertGreaterEqual(mobile_left['x'], 0)
                    self.assertLessEqual(mobile_right['x'] + mobile_right['width'], 375)
                    page.set_viewport_size({'width': 1200, 'height': 900})
                page.locator('#username').fill('missing')
                page.locator('#searchButton').click()
                page.wait_for_function("!document.getElementById('searchButton').disabled")
                self.assertIn('TikTok solicita verificación.', page.locator('#statusMessage').inner_text())
                self.assertTrue(page.locator('#downloadJSON').is_disabled())
                self.assertTrue(page.locator('#downloadCSV').is_disabled())
                self.assertTrue(page.locator('#dashboard').is_hidden())
                for text in ['+SUM(1)', '-1+2', '@SUM(1)', '  =1', '\t=1', '\n=1']:
                    cell = page.evaluate('value => csvCell(value)', text)
                    self.assertTrue(next(csv.reader([cell]))[0].startswith("'"))
                self.assertEqual(calls, ['test_only', 'empty_profile', 'missing'])
                load.assert_not_called()
                self.assertEqual(errors, [])
            finally:
                browser.close()
