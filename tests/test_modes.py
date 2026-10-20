import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from playwright.sync_api import Error as PlaywrightError

from backend import demo, main, scraper, session


def sample_profile():
    # Synthetic test data is never installed as a demo capture.
    return {
        'username': 'test_only', 'nickname': 'Test fixture', 'followers': '20',
        'following': '3', 'likes': '100', 'bio': '',
        'url': 'https://www.tiktok.com/@test_only?token=secret',
        'avatar_url': 'https://cdn.invalid/avatar?token=secret',
        'followers_users': ['test_reader'], 'following_users': [],
        'videos': [dict(id=str(100 + i), url=f'https://www.tiktok.com/@test_only/video/{100+i}?token=secret',
                        preview_url='https://cdn.invalid/cover?token=secret', title=f'Test {i}',
                        views=str(i), likes='0', comments='1', shares='0', saves='0',
                        comments_list=[{'username': 'test_reader', 'text': 'Test comment', 'cookies': 'secret'}])
                   for i in range(10)],
        '_meta': {'mode': 'real', 'warnings': []}, 'cookies': 'secret',
    }


async def request(path, query=b''):
    events = []
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
             'method': 'GET', 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
             'query_string': query, 'headers': [], 'client': ('127.0.0.1', 123),
             'server': ('127.0.0.1', 8000), 'root_path': ''}
    received = False
    async def receive():
        nonlocal received
        if received:
            await asyncio.Event().wait()
        received = True
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    async def send(event):
        events.append(event)
    await asyncio.wait_for(main.app(scope, receive, send), timeout=5)
    status = next(e['status'] for e in events if e['type'] == 'http.response.start')
    body = b''.join(e.get('body', b'') for e in events if e['type'] == 'http.response.body')
    return status, json.loads(body)


class SessionTests(unittest.TestCase):
    def test_private_permissions_lock_and_release(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, 'PRIVATE_DIR', Path(folder) / 'private'):
            with session.profile_lock() as profile:
                self.assertEqual(stat.S_IMODE(profile.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(profile.parent.stat().st_mode), 0o700)
                with self.assertRaises(session.SessionBusyError):
                    with session.profile_lock():
                        self.fail('Second browser must not start')
                code = 'from backend.session import profile_lock, SessionBusyError\ntry:\n with profile_lock(): pass\nexcept SessionBusyError: raise SystemExit(23)'
                code = f'from pathlib import Path\nimport backend.session as s\ns.PRIVATE_DIR=Path({str(profile.parent)!r})\n' + code
                result = subprocess.run([__import__('sys').executable, '-B', '-c', code], capture_output=True)
                self.assertEqual(result.returncode, 23)
            with session.profile_lock():
                pass

    def test_official_context_reuses_directory_and_headless_default(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, 'PRIVATE_DIR', Path(folder) / 'private'), patch.object(session, 'sync_playwright') as driver:
            launch = driver.return_value.__enter__.return_value.chromium.launch_persistent_context
            for _ in range(2):
                with session.persistent_context():
                    pass
            self.assertEqual(launch.call_count, 2)
            self.assertEqual(launch.call_args_list[0], launch.call_args_list[1])
            self.assertTrue(launch.call_args.kwargs['headless'])
            launch.return_value.close.assert_called()

    def test_driver_errors_do_not_leak_private_details(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, 'PRIVATE_DIR', Path(folder) / 'private'), patch.object(session, 'sync_playwright') as driver:
            driver.return_value.__enter__.return_value.chromium.launch_persistent_context.side_effect = PlaywrightError('password=secret')
            with self.assertRaises(RuntimeError) as error:
                with session.persistent_context():
                    pass
            self.assertNotIn('secret', str(error.exception))
            with session.profile_lock():
                pass

    @patch.object(session, 'persistent_context')
    def test_visible_setup_is_separate_and_manual(self, persistent):
        context = persistent.return_value.__enter__.return_value
        context.pages = [Mock()]
        with patch('builtins.input', return_value=''), patch('builtins.print'):
            session.configure_session()
        persistent.assert_called_once_with(headless=False)
        context.pages[0].goto.assert_called_once()


class CaptureTests(unittest.TestCase):
    def test_roundtrip_ten_videos_and_allowlisted_fields(self):
        original = sample_profile()
        with tempfile.TemporaryDirectory() as folder, patch.object(demo, 'CAPTURE_DIR', Path(folder) / 'captures'):
            path = demo.save_capture(original)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            raw = path.read_text()
            self.assertNotIn('secret', raw)
            self.assertNotIn('cookies', raw)
            restored = demo.load_capture('test_only')
            self.assertEqual(len(restored['videos']), 10)
            self.assertEqual(set(restored), set(original) - {'cookies'})
            for before, after in zip(original['videos'], restored['videos']):
                self.assertEqual(set(before), set(after))
                for key in demo.VIDEO_FIELDS:
                    self.assertEqual(before[key], after[key])
                self.assertEqual(after['comments_list'], [{'username': 'test_reader', 'text': 'Test comment'}])
            self.assertEqual(restored['_meta']['mode'], 'demo')
            self.assertIn('captured_at', restored['_meta'])
            with self.assertRaises(RuntimeError):
                demo.save_capture(original)
            self.assertEqual(path.read_text(), raw)

    def test_no_capture_and_no_browser_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(demo, 'CAPTURE_DIR', Path(folder) / 'captures'), patch.object(main, 'scrape_profile') as scrape:
            status, body = asyncio.run(request('/api/profile/test_only', b'mode=demo'))
            self.assertEqual(status, 404)
            self.assertIn('No hay una captura', body['detail'])
            scrape.assert_not_called()

    def test_invalid_capture_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(demo, 'CAPTURE_DIR', Path(folder) / 'captures'):
            path = demo.save_capture(sample_profile())
            record = json.loads(path.read_text())
            record['profile']['username'] = 'another_user'
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(RuntimeError, 'formato inválido'):
                demo.load_capture('test_only')

    def test_demo_data_cannot_be_saved_as_real(self):
        profile = sample_profile()
        profile['_meta']['mode'] = 'demo'
        with self.assertRaises(ValueError):
            demo.save_capture(profile)


class ModeAPITests(unittest.TestCase):
    @patch.object(main, 'load_capture')
    @patch.object(main, 'scrape_profile', return_value=sample_profile())
    def test_default_and_explicit_real(self, scrape, load):
        for query in (b'', b'mode=real'):
            status, data = asyncio.run(request('/api/profile/test_only', query))
            self.assertEqual(status, 200)
            self.assertEqual(data['videos'], sample_profile()['videos'])
            self.assertEqual(data['_meta']['mode'], 'real')
        load.assert_not_called()
        self.assertEqual(scrape.call_count, 2)

    @patch.object(main, 'scrape_profile')
    @patch.object(main, 'load_capture', return_value={'username': 'test_only', '_meta': {'mode': 'demo'}})
    def test_demo_selection(self, load, scrape):
        status, data = asyncio.run(request('/api/profile/test_only', b'mode=demo'))
        self.assertEqual((status, data['_meta']['mode']), (200, 'demo'))
        scrape.assert_not_called()

    @patch.object(main, 'scrape_profile')
    @patch.object(main, 'load_capture')
    def test_invalid_mode_never_queries_sources(self, load, scrape):
        status, _ = asyncio.run(request('/api/profile/test_only', b'mode=unknown'))
        self.assertEqual(status, 422)
        scrape.assert_not_called()
        load.assert_not_called()

    @patch.object(main, 'scrape_profile')
    def test_errors_are_clear_and_never_trigger_demo(self, scrape):
        errors = [(session.SessionBusyError('Sesión en uso'), 409),
                  (scraper.TikTokPageError('TikTok solicita verificación'), 502),
                  (ValueError('Invalid username'), 400), (OSError('private path'), 503)]
        with patch.object(main, 'load_capture') as load:
            for error, expected in errors:
                with self.subTest(error=type(error).__name__):
                    scrape.side_effect = error
                    status, data = asyncio.run(request('/api/profile/test_only'))
                    self.assertEqual(status, expected)
                    self.assertNotIn('private path', data['detail'])
            load.assert_not_called()


class RealFlowTests(unittest.TestCase):
    def test_scrape_keeps_ten_video_flow_and_headless(self):
        profile = sample_profile()
        context = Mock()
        context.new_page.return_value.goto.return_value.status = 200
        @contextmanager
        def persistent(**kwargs):
            self.assertEqual(kwargs, {'headless': True})
            yield context
        cards = [{'id': v['id'], 'url': v['url']} for v in profile['videos']]
        with patch.object(scraper, 'persistent_context', persistent), patch.object(scraper, 'validate_content_page'), patch.object(scraper, 'extract_profile_data', return_value={k: v for k, v in profile.items() if k != 'cookies'}), patch.object(scraper, 'extract_user_list', return_value=[]), patch.object(scraper, 'get_profile_video_cards', return_value=cards), patch.object(scraper, 'extract_latest_videos', return_value=profile['videos']) as videos:
            result = scraper.scrape_profile('test_only')
        self.assertEqual(len(result['videos']), 10)
        self.assertEqual(result['_meta']['mode'], 'real')
        self.assertEqual(videos.call_args.args, (context, cards))


if __name__ == '__main__':
    unittest.main()
