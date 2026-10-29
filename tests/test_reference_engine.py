"""Integrated original engine tests. All browser traffic is intercepted offline."""
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend import main, reference_engine, reference_runtime, scraper, session
from backend.reference_adapter import adapt_profile
from backend.normalizer import normalize_profile
from backend.repository import ProfileRepository
from backend.vendor.scrapingtiktok import tiktok_scraper as original
from test_repository import MemoryDatabase

OWNER = {'uniqueId': 'example', 'id': '42', 'secUid': 'public-example'}


def raw_profile():
    return {'success': True, 'username': 'example', 'user_id': '42', 'sec_uid': 'public-example',
            'followers_count': 1234567, 'following_count': 0, 'heart_count': None,
            'followers_list': [{'username': 'reader'}, {'username': 'READER'}], 'following_list': [],
            'videos': [{'_verified': True, 'video_id': '333', 'video_url': 'https://www.tiktok.com/@example/video/333',
                        'description': 'Text', 'create_time': 1700000000, 'views_count': 2345678,
                        'likes_count': 0, 'comments_count': 20, 'shares_count': None,
                        'comments': [{'comment_id': '5', 'username': 'reader', 'text': 'Network', 'likes_count': 0},
                                     {'comment_id': '', 'username': 'dom', 'text': 'DOM', 'likes_count': None}]}]}


class AdapterTests(unittest.TestCase):
    def test_pristine_upstream_copy_and_mit_license_are_preserved(self):
        root = Path(original.__file__).parent
        digest = hashlib.sha256((root / 'upstream' / 'tiktok_scraper.py').read_bytes()).hexdigest()
        self.assertEqual(digest, 'b836bbc154b29a96abc491313ddb1409a1a5240be977c2dc37baef292459ad0a')
        license_text = (root / 'LICENSE').read_text()
        self.assertIn('MIT License', license_text)
        self.assertIn('Copyright (c) 2026 Jccasav', license_text)

    def test_unknowns_exact_values_identity_dates_and_comments_survive_mongo(self):
        profile = adapt_profile(raw_profile(), 'example')
        self.assertEqual(profile['followers'], 1234567)
        self.assertEqual(profile['following'], 0)
        self.assertIsNone(profile['likes'])
        self.assertEqual(profile['followers_users'], ['reader'])
        documents = normalize_profile(profile)
        self.assertEqual(documents['publications'][0]['created_at'], 1700000000)
        self.assertEqual(documents['publications'][0]['author'], OWNER)
        self.assertEqual(documents['publications'][0]['metrics']['views'], 2345678)
        self.assertIsNone(documents['publications'][0]['metrics']['shares'])
        self.assertEqual(documents['comments'][0]['comment_id'], '5')
        self.assertIsNone(documents['comments'][1]['comment_id'])
        self.assertNotIn('digg_count', documents['comments'][1])
        database = MemoryDatabase()
        ProfileRepository(database).save(documents)
        self.assertEqual(len(database['comments'].rows), 2)
        self.assertEqual(database['extraction_runs'].rows[0]['snapshot']['extraction_metadata']['engine'], 'SCRAPINGTIKTOK')

    def test_failures_never_become_zero_profiles(self):
        for raw in ({'success': False, 'error': 'token=SECRET'}, {}, None):
            with self.assertRaises(RuntimeError) as error:
                adapt_profile(raw, 'example')
            self.assertNotIn('SECRET', str(error.exception))

    def test_foreign_profile_or_video_and_unverified_fallback_id(self):
        raw = raw_profile()
        with self.assertRaises(reference_runtime.IdentityError):
            adapt_profile(raw, 'other')
        raw['videos'][0]['video_url'] = 'https://www.tiktok.com/@other/video/333'
        with self.assertRaises(reference_runtime.IdentityError):
            adapt_profile(raw, 'example')
        raw['videos'][0].pop('_verified')
        self.assertEqual(adapt_profile(raw, 'example')['videos'], [])

    def test_comment_responses_require_exact_host_endpoint_and_publication(self):
        for url, accepted in (
            ('https://www.tiktok.com/api/comment/list/?aweme_id=333', True),
            ('https://www.tiktok.com/api/comment/list/?aweme_id=999', False),
            ('https://www.tiktok.com/api/comment/list/', False),
            ('https://www.tiktok.com/api/comment/list/?aweme_id=333&aweme_id=999', False),
            ('https://foreign.invalid/api/comment/list/?aweme_id=333', False),
            ('https://www.tiktok.com/api/comment/list/reply/?aweme_id=333', False),
        ):
            response = Mock(url=url, status=200)
            self.assertEqual(reference_runtime.comment_response_matches(response, raw_profile()['videos'][0]['video_url']), accepted)

    def test_user_response_requires_profile_identity_and_current_scene(self):
        for query, accepted in (('scene=67&secUid=public-example', True), ('scene=21&secUid=public-example', False),
                                ('scene=67', False), ('scene=67&secUid=other', False),
                                ('scene=67&secUid=public-example&userId=99', False)):
            response = Mock(url='https://www.tiktok.com/api/user/list/?' + query, status=200)
            self.assertEqual(reference_runtime.user_response_matches(response, OWNER, '67'), accepted)

    def test_profile_lock_is_kept_by_the_new_engine(self):
        with patch.object(reference_runtime, 'profile_lock', side_effect=session.SessionBusyError('busy')):
            with self.assertRaises(session.SessionBusyError):
                reference_engine.scrape_profile('example')

    def test_upstream_functions_remain_present_and_no_old_engine_is_called(self):
        for name in ('_setup_context', 'scrape', '_extract_video_urls', '_extract_single_video_details'):
            self.assertTrue(asyncio.iscoroutinefunction(getattr(original.TikTokScraper, name)))
        raw = raw_profile()
        with patch.object(original.TikTokScraper, 'scrape', new=AsyncMock(return_value=raw)) as extract, \
             patch.object(scraper, 'scrape_profile', side_effect=AssertionError('old engine invoked')), \
             patch.object(main, 'save_profile') as save, patch.object(main, 'print_profile'):
            profile = main.get_profile('example', 'real')
        extract.assert_awaited_once_with('example', max_list_items=30, max_videos=10, max_comments_per_video=20)
        save.assert_called_once_with(profile)
        self.assertEqual(profile['_meta']['engine'], 'SCRAPINGTIKTOK')


class OriginalBrowserTests(unittest.TestCase):
    def fixture_setup(self, mode='normal'):
        async def setup(engine, playwright):
            browser, context = await reference_runtime.setup_persistent_context(engine, playwright)
            engine._launch_count = getattr(engine, '_launch_count', 0) + 1
            item = {'id': '333', 'author': OWNER, 'createTime': 1700000000, 'desc': 'Original engine',
                    'stats': {'diggCount': 0, 'commentCount': 2, 'shareCount': 0},
                    'statsV2': {'playCount': '1234567'}, 'video': {'cover': 'https://fixture.invalid/image'}}
            profile = {'__DEFAULT_SCOPE__': {'webapp.user-detail': {'userInfo': {
                'user': OWNER, 'statsV2': {'followerCount': '1234567', 'followingCount': '1', 'heartCount': '0'}}}}}
            detail = {'__DEFAULT_SCOPE__': {'webapp.video-detail': {'itemInfo': {'itemStruct': item}}}}
            profile_html = f'''<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{json.dumps(profile)}</script>
              <strong data-e2e="followers-count" onclick="fetch('/api/user/list/?scene=67&secUid=public-example')">2</strong>
              <strong data-e2e="following-count" onclick="fetch('/api/user/list/?scene=21&secUid=public-example')">1</strong>
              <a href="https://www.tiktok.com/@example/video/333">Own</a>
              <a href="https://www.tiktok.com/@other/video/999">Foreign</a><script>localStorage.setItem('fixture_session', 'present')</script>'''
            video_html = f'''<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{json.dumps(detail)}</script>
              <button data-e2e="comment-count" onclick="fetch('/api/comment/list/?aweme_id=333');fetch('/api/comment/list/?aweme_id=999')">Comments</button>
              <div class="DivCommentItemContainer"><a data-e2e="comment-username" href="/@dom">Display Name</a>
              <p class="PCommentText">DOM text</p></div><script>if(localStorage.getItem('fixture_session') !== 'present') document.querySelector('script#__UNIVERSAL_DATA_FOR_REHYDRATION__').remove()</script>'''
            async def route_request(route):
                url = route.request.url
                if mode == 'captcha':
                    await route.fulfill(content_type='text/html', body='<div id="captcha-test">Manual verification</div>')
                elif '/api/user/list/' in url:
                    await route.fulfill(json={'statusCode': 0, 'userList': [{'user': {'uniqueId': 'follower' if 'scene=67' in url else 'following'}}]})
                elif '/api/comment/list/' in url:
                    await route.fulfill(json={'status_code': 0, 'comments': [{'cid': '5' if 'aweme_id=333' in url else '999',
                        'aweme_id': '333' if 'aweme_id=333' in url else '999',
                        'user': {'unique_id': 'network'}, 'text': 'Network text'}]})
                else:
                    await route.fulfill(content_type='text/html', body=video_html if '/video/' in url else profile_html)
            await engine._shared_context.route('**/*', route_request)
            return browser, context
        return setup

    def test_original_engine_full_flow_persistent_session_adapter_and_endpoint(self):
        database = MemoryDatabase()
        with tempfile.TemporaryDirectory() as folder, patch.object(session, 'PRIVATE_DIR', Path(folder) / 'private'), \
             patch.object(original, 'setup_persistent_context', side_effect=self.fixture_setup()), \
             patch.object(original, 'asyncio', SimpleNamespace(sleep=AsyncMock())), \
             patch.object(main, 'save_profile', side_effect=lambda profile: ProfileRepository(database).save(normalize_profile(profile))), \
             patch.object(main, 'print_profile'), \
             patch.object(scraper, 'scrape_profile', side_effect=AssertionError('legacy invoked')):
            profile = main.get_profile('example', 'real')
        self.assertEqual(profile['followers'], 1234567)
        self.assertEqual(profile['likes'], 0)
        self.assertEqual(profile['followers_users'], ['follower'])
        self.assertEqual(profile['following_users'], ['following'])
        self.assertEqual([video['id'] for video in profile['videos']], ['333'])
        self.assertEqual(profile['videos'][0]['views'], 1234567)
        self.assertIsNone(profile['videos'][0]['saves'])
        comments = profile['videos'][0]['comments_list']
        self.assertEqual({comment['username'] for comment in comments}, {'network', 'dom'})
        self.assertEqual([comment.get('cid') for comment in comments if comment.get('cid')], ['5'])
        self.assertEqual(len(database['comments'].rows), 2)
        self.assertEqual(len(database['extraction_runs'].rows), 1)

    def test_captcha_aborts_original_broad_catches_and_does_not_persist(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, 'PRIVATE_DIR', Path(folder) / 'private'), \
             patch.object(original, 'setup_persistent_context', side_effect=self.fixture_setup('captcha')), \
             patch.object(main, 'save_profile') as save:
            with self.assertRaises(main.HTTPException) as error:
                main.get_profile('example', 'real')
            self.assertEqual(error.exception.status_code, 502)
            self.assertIn('verificación', error.exception.detail)
            save.assert_not_called()
            with session.profile_lock():
                pass
        # The session lock is released even when the original engine aborts.
