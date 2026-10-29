"""Ten-comment regression: local intercepted responses, existing engine, fake DB."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from backend.reference_runtime import SharedBrowser, IdentityError
from backend.research_diagnostics import LOGGER
from backend.research_models import StudyCreate
from backend.research_repository import ResearchRepository
from backend.research_sources import Page, SourceFailure
from backend.research_tiktok import TikTokConnector
from backend.research_worker import ResearchWorker
from backend.vendor.scrapingtiktok import tiktok_scraper as original
from research_fake import Database

URL = 'https://www.tiktok.com/@example/video/333'


@contextmanager
def controlled_acquisition(mode):
    handles = []
    async def setup(engine, playwright):
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        engine._shared_context = context
        handles.append((context, browser))
        async def route_request(route):
            path = urlsplit(route.request.url).path
            if path == '/api/comment/list/' and 'cursor=10' in route.request.url:
                await route.fulfill(status=403, body='blocked fixture')
            elif path == '/api/comment/list/' and 'aweme_id=333' in route.request.url:
                if mode == 'comments503empty':
                    await route.fulfill(status=503, body='Unavailable fixture')
                    return
                comments = [{'cid': str(i+1), 'aweme_id': '333',
                    'text': f'Comentario educativo {i} persona@example.invalid @lector',
                    'user': {'unique_id': 'reader'}} for i in range(10)]
                comments += [comments[0], {**comments[0], 'cid': '999', 'aweme_id': '444'}]
                await route.fulfill(json={'status_code': 0, 'aweme_id': '333',
                    'comments': [] if mode == 'rehydration_only' else comments})
            elif path == '/secondary':
                if mode == 'aborted_js':
                    await route.abort('failed')
                else:
                    await route.fulfill(status=429 if mode == 'secondary429' else 403, body='blocked fixture')
            elif path == '/api/comment/list/':
                await route.fulfill(status=403, body='blocked fixture')
            elif path.startswith('/@example/video/'):
                item = {'id': '333', 'author': {'uniqueId': 'wrong' if mode == 'foreign' else 'example'},
                    'desc': 'Descripción educativa', 'stats': {'playCount': 10}}
                data = {'__DEFAULT_SCOPE__': {'webapp.video-detail': {'itemInfo': {'itemStruct': item}}}}
                if mode == 'rehydration_only':
                    data['__DEFAULT_SCOPE__']['webapp.video-detail']['comments'] = [
                        {'cid': str(i), 'text': 'Not an engine comment'} for i in range(10)]
                action = 'fetch("/secondary?token=SECRET")'
                if mode == 'comments403':
                    action = 'fetch("/api/comment/list/?aweme_id=333&cursor=10&token=SECRET")'
                elif mode == 'other_video403':
                    action = 'fetch("/api/comment/list/?aweme_id=444&token=SECRET")'
                elif mode in ('captcha', 'login'):
                    marker = 'id="captcha-visible"' if mode == 'captcha' else 'data-e2e="login-modal"'
                    action = 'document.body.insertAdjacentHTML("beforeend", '+json.dumps('<div '+marker+'>Gate</div>')+')'
                elif mode == 'aborted_js':
                    action += ';setTimeout(() => {throw new TypeError("SECRET private message")}, 0)'
                # Completion of the first request precedes the error/gate. Engine sleeps
                # below give its real response interceptor time to validate ten comments.
                script = 'async function load(){await (await fetch("/api/comment/list/?aweme_id=333")).text();'+action+';}'
                body = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'+json.dumps(data)+'</script><script>'+script+'</script><button data-e2e="comment-icon" onclick="load()">Comments</button>'
                if mode == 'initialcaptcha':
                    body = '<div id="captcha-visible">Gate</div>'
                await route.fulfill(status=403 if mode == 'main403' else 200, content_type='text/html', body=body)
            else:
                await route.fulfill(status=404, body='unused fixture')
        await context.route('**/*', route_request)
        shared = SharedBrowser(context)
        return shared, await shared.new_context()

    @asynccontextmanager
    async def runtime(engine):
        async with async_playwright() as playwright:
            try:
                yield playwright
            finally:
                for context, browser in handles:
                    await context.close()
                    await browser.close()

    async def brief_sleep(*args):
        await asyncio.sleep(0.1)

    with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED': '1', 'MEDIA_SCRAPER_TIKTOK_DEBUG': '0'}), \
         patch('backend.research_tiktok.persistent_playwright', runtime), \
         patch.object(original.TikTokScraper, '_setup_context', setup), \
         patch.object(original, 'asyncio', SimpleNamespace(sleep=AsyncMock(side_effect=brief_sleep))):
        yield


class AcquisitionAccessTests(unittest.TestCase):
    def read(self):
        config = StudyCreate(topic='fixture', source='tiktok').source_config.model_dump()
        config['max_comments_per_publication'] = 10
        return TikTokConnector().read(topic='fixture', config=config, kind='acquire',
            publication_id=URL, cursor=None, limit=10, attempt=1)

    def test_ten_comments_survive_secondary_403_429_and_js_abort(self):
        for mode in ('secondary403', 'secondary429', 'aborted_js', 'other_video403'):
            with self.subTest(mode=mode), controlled_acquisition(mode), self.assertLogs(LOGGER, level='INFO') as logs:
                page = self.read()
            self.assertEqual(len(page.items), 10)
            self.assertEqual(len({row['record_id'] for row in page.items}), 10)
            self.assertTrue(all('username' not in row for row in page.items))
            events = [record.event for record in logs.records]
            self.assertTrue(any(e['event'] == 'comments_observed' and e['received'] == 10 and e['publication_verified'] for e in events))
            decision = next(e for e in events if e['event'] == 'acquisition_access_decision')
            self.assertFalse(decision['restriction_confirmed'])
            self.assertEqual(decision['snapshots']['before']['http_status'], 200)
            self.assertEqual(decision['snapshots']['after']['classification'], 'video_document')
            if mode == 'aborted_js':
                self.assertGreaterEqual(decision['snapshots']['after']['browser_errors']['javascript_errors'], 1)
                self.assertGreaterEqual(decision['snapshots']['after']['browser_errors']['failed_requests'], 1)
            else:
                self.assertGreaterEqual(decision['secondary_http_errors'], 1)
            self.assertNotIn('SECRET', json.dumps(events))
            self.assertNotIn('persona@example.invalid', json.dumps(events))

    def test_ten_observed_comments_still_reject_confirmed_restrictions(self):
        for mode, reason in (('comments403', 'http_target_comments'), ('main403', 'http_main_document'),
                             ('captcha', 'captcha_or_verification'), ('login', 'authentication')):
            with self.subTest(mode=mode), controlled_acquisition(mode), self.assertLogs(LOGGER, level='INFO') as logs:
                with self.assertRaises(SourceFailure) as caught:
                    self.read()
            self.assertEqual(caught.exception.code, 'access_restricted')
            events = [record.event for record in logs.records]
            self.assertTrue(any(e['event'] == 'comments_observed' and e['received'] == 10 for e in events))
            decision = next(e for e in events if e['event'] == 'acquisition_access_decision')
            self.assertTrue(decision['restriction_confirmed'])
            self.assertIn(reason, [e['reason'] for e in decision['confirmed_evidence']])
            self.assertFalse(any(e['event'] == 'comments_processed' for e in events))

    def test_rehydration_verifies_video_but_does_not_supply_comments(self):
        with controlled_acquisition('rehydration_only'), self.assertLogs(LOGGER, level='INFO') as logs:
            page = self.read()
        self.assertEqual(page.items, [])
        observed = next(record.event for record in logs.records if record.event['event'] == 'comments_observed')
        self.assertTrue(observed['publication_verified'])
        self.assertEqual(observed['received'], 0)

    def test_foreign_video_author_remains_rejected(self):
        with controlled_acquisition('foreign'), self.assertRaises(SourceFailure) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'invalid_provenance')

    def test_original_engine_access_guard_remains_active(self):
        with controlled_acquisition('initialcaptcha'), self.assertLogs(LOGGER, level='INFO') as logs:
            with self.assertRaises(SourceFailure) as caught:
                self.read()
        self.assertEqual(caught.exception.code, 'access_restricted')
        decision = next(record.event for record in logs.records if record.event['event'] == 'acquisition_access_decision')
        self.assertTrue(decision['engine_access_guard'])
        self.assertTrue(decision['restriction_confirmed'])
        self.assertEqual(decision['snapshots']['after']['classification'], 'captcha_or_verification')

    def test_failed_comments_response_does_not_mark_empty_video_as_processed(self):
        with controlled_acquisition('comments503empty'), self.assertLogs(LOGGER, level='INFO') as logs, self.assertRaises(SourceFailure) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'source_load_timeout')
        self.assertTrue(caught.exception.retryable)
        error = next(record.event for record in logs.records if record.event['event'] == 'acquisition_http_error')
        self.assertEqual(error['scope'], 'target_comments')
        self.assertFalse(error['establishes_access_restriction'])

    def test_worker_stages_only_successful_acquisition(self):
        for mode, expected in (('secondary403', 10), ('comments403', 0)):
            with self.subTest(mode=mode):
                repository = ResearchRepository(Database())
                identity = repository.create(StudyCreate(topic='fixture', source='tiktok',
                    source_config={'max_comments_per_publication': 10}))['study_id']
                repository.control(identity, 'start')
                discovery = Mock()
                discovery.read.return_value = Page('tiktok', 'discover', None, None, None, [{'publication_id': URL}])
                ResearchWorker(repository, discovery).tick()
                with controlled_acquisition(mode), patch.object(repository, 'stage_page', wraps=repository.stage_page) as stage, \
                     patch.object(repository, 'confirm_page', wraps=repository.confirm_page) as confirm:
                    ResearchWorker(repository, TikTokConnector()).tick()
                detail = repository.detail(identity)
                self.assertEqual(detail['counters']['prepared'], expected)
                self.assertEqual(repository.records.count_documents({'study_id': identity}), expected)
                if expected:
                    stage.assert_called_once()
                    confirm.assert_called_once()
                    self.assertEqual(detail['counters']['publications_processed'], 1)
                    self.assertNotIn('persona@example.invalid', str(repository.record_page(identity)))
                else:
                    stage.assert_not_called()
                    confirm.assert_not_called()
                    self.assertEqual(detail['status'], 'paused')
                    self.assertEqual(detail['last_error'], 'access_restricted')
                    task = repository.tasks.find_one({'study_id': identity, 'kind': 'acquire'})
                    self.assertIsNone(task['cursor'])
                    self.assertIsNone(task['pending'])
