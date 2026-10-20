"""Offline fixtures based on the supplied grid HTML; no live TikTok queries."""

from contextlib import contextmanager
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from playwright.sync_api import sync_playwright

from backend import scraper
from test_modes import sample_profile
from test_scraper import content_page, video

AUTHOR = {'uniqueId': 'example', 'id': '42', 'secUid': 'public-example'}


def post(post_id='333', kind='photo', date=1700000000, **changes):
    item = {'id': post_id, 'author': dict(AUTHOR), 'desc': f'Own {kind} {post_id} ñ 🎵',
            'stats': {'diggCount': 12, 'commentCount': 4, 'shareCount': 0, 'collectCount': 2}}
    if kind == 'photo':
        item['imagePost'] = {'images': [{'imageURL': {'urlList': ['https://fixture.invalid/photo.jpg']}}]}
    else:
        item['video'] = {'cover': 'https://fixture.invalid/video.jpg'}
        item['stats']['playCount'] = 2000
    if date is not None:
        item['createTime'] = date
    item.update(changes)
    return item


def cards(items):
    return [{'id': item['id'], 'type': 'photo' if 'imagePost' in item else 'video',
             'url': f'https://www.tiktok.com/@example/{"photo" if "imagePost" in item else "video"}/{item["id"]}'}
            for item in items]


class PublicationTests(unittest.TestCase):
    def details(self, payloads, url='https://www.tiktok.com/@example/photo/333', expected=AUTHOR):
        with patch.object(scraper, 'get_embedded_json', return_value=payloads), patch.object(scraper, 'extract_video_comments', return_value=[]):
            return scraper.extract_video_details(content_page(), url, expected_author=expected)

    def process(self, items, profile_payloads=()):
        context = Mock()
        pages = []
        by_id = {item['id']: item for item in items}
        def new_page():
            page = content_page()
            def goto(url, **kwargs):
                page.url = url
                return Mock(status=200)
            page.goto.side_effect = goto
            pages.append(page)
            return page
        context.new_page.side_effect = new_page
        warnings = []
        with patch.object(scraper, 'get_embedded_json', side_effect=lambda page: [by_id[page.url.rsplit('/', 1)[-1]]]), patch.object(scraper, 'extract_video_comments', return_value=[]):
            result = scraper.extract_latest_videos(context, cards(items), warnings, AUTHOR, profile_payloads)
        for page in pages:
            page.close.assert_called_once()
        return result, warnings, pages

    def test_video_and_photo_keep_types_metrics_and_exact_id(self):
        for kind in ('video', 'photo'):
            with self.subTest(kind=kind):
                item = post(kind=kind)
                unrelated = post('999', kind='video', author={'uniqueId': 'other', 'id': '99'})
                result = self.details([unrelated, item], f'https://www.tiktok.com/@example/{kind}/333')
                self.assertEqual(result['type'], kind)
                self.assertEqual(result['title'], item['desc'])
                self.assertEqual(result['likes'], '12')
                self.assertEqual(result['comments'], '4')
                self.assertEqual(result['views'], '2.0K' if kind == 'video' else 'N/A')
                self.assertEqual(result['preview_url'], f'https://fixture.invalid/{kind}.jpg')

    def test_unknown_foreign_and_contradictory_authors_are_rejected(self):
        for change, message in [({'author': {}}, 'no verificable'),
                                ({'author': {'uniqueId': 'other', 'id': '99'}}, 'contradictoria'),
                                ({'authorId': '99'}, 'contradictoria')]:
            with self.subTest(change=change), self.assertRaisesRegex(scraper.TikTokPageError, message):
                self.details([post(**change)])

    def test_named_foreign_url_is_not_rewritten_to_requested_username(self):
        with self.assertRaisesRegex(scraper.TikTokPageError, 'enlace'):
            self.details([post()], 'https://www.tiktok.com/@other/photo/333')

    def test_confirmed_numeric_user_id_in_url_can_match_profile_identity(self):
        result = self.details([post()], 'https://www.tiktok.com/@42/photo/333')
        self.assertEqual(result['url'], 'https://www.tiktok.com/@42/photo/333')
        with self.assertRaisesRegex(scraper.TikTokPageError, 'enlace'):
            self.details([post()], 'https://www.tiktok.com/@99/photo/333')

    def test_conflicting_duplicate_author_records_are_rejected(self):
        with self.assertRaisesRegex(scraper.TikTokPageError, 'contradictoria'):
            self.details([post(), post(author={'id': '99'})])
        with self.assertRaisesRegex(scraper.TikTokPageError, 'contradictoria'):
            self.details([post(), post(author={'id': '99'})], expected={'uniqueId': 'example'})

    def test_missing_metrics_do_not_borrow_from_recommendations(self):
        item = post()
        item.pop('stats')
        result = self.details([post('999', kind='video'), item])
        for key in ('views', 'likes', 'comments', 'shares', 'saves'):
            self.assertEqual(result[key], 'N/A')
        with self.assertRaisesRegex(scraper.TikTokPageError, 'no verificable'):
            self.details([post('999')])

    def test_sigi_string_author_is_resolved_without_guessing_numeric_user_id(self):
        item = post(author='user_reference')
        result = self.details([{'ItemModule': {'333': item}, 'UserModule': {'users': {'user_reference': AUTHOR}}}])
        self.assertEqual(result['likes'], '12')
        numeric_name = '6911308753925293062'
        self.assertEqual(self.details([post(author=numeric_name)], f'https://www.tiktok.com/@{numeric_name}/photo/333', expected={'uniqueId': numeric_name, 'id': '42'})['likes'], '12')

    def test_profile_user_identifiers_are_not_video_identifiers(self):
        payload = {'__DEFAULT_SCOPE__': {'webapp.user-detail': {'userInfo': {'user': AUTHOR}}}}
        self.assertEqual(scraper.profile_author([payload], 'example'), AUTHOR)
        item = post()
        item.pop('author')
        with self.assertRaisesRegex(scraper.TikTokPageError, 'no verificable'):
            self.details([item], expected={'uniqueId': 'example', 'id': '333'})

    def test_dates_order_all_loaded_posts_and_pinned_post_is_not_treated_as_new(self):
        items = [post('100', date=1600000000, isPinnedItem=True)] + [post(str(101+i), kind='video' if i % 2 else 'photo', date=1700000000+i) for i in range(12)]
        result, warnings, pages = self.process(items)
        self.assertEqual([item['id'] for item in result], [str(112-i) for i in range(10)])
        self.assertTrue(any('fijadas' in text for text in warnings))
        self.assertEqual(len(pages), 13)
        self.assertTrue(all('created_at' not in item for item in result))

    def test_profile_dates_avoid_opening_posts_older_than_tenth_verified_post(self):
        items = [post(str(100+i), date=1700000000+i) for i in range(15)]
        items[0]['isPinnedItem'] = True
        result, warnings, pages = self.process(items, profile_payloads=[{'ItemModule': {item['id']: item for item in items}}])
        self.assertEqual([item['id'] for item in result], [str(114-i) for i in range(10)])
        self.assertEqual(len(pages), 10)
        self.assertTrue(any('fijadas' in text for text in warnings))

    def test_rejected_posts_do_not_consume_limit_of_ten_verified_posts(self):
        items = [post(str(100+i), date=1700000000+i) for i in range(14)]
        for item in items[:3]:
            item['author'] = {'uniqueId': 'other', 'id': '99'}
        result, warnings, _ = self.process(items)
        self.assertEqual([item['id'] for item in result], [str(113-i) for i in range(10)])
        self.assertEqual(sum('descartada' in warning for warning in warnings), 3)

    def test_missing_dates_preserve_grid_order_with_explicit_warning(self):
        items = [post('100', date=1700000001, isPinnedItem=True), post('101', date=None), post('102', date=1700000002)]
        result, warnings, _ = self.process(items)
        self.assertEqual([item['id'] for item in result], ['100', '101', '102'])
        self.assertTrue(any('sin garantizar' in text for text in warnings))
        self.assertTrue(any('fijadas' in text for text in warnings))

    def test_conflicting_or_invalid_dates_are_not_invented(self):
        item = post()
        _, _, metadata = scraper.publication_evidence([item, post(date=1700000001)], '333', AUTHOR)
        self.assertIsNone(metadata['created_at'])
        for date in (True, 0, 'not a date', 1700000000000, int(scraper.time())+10000):
            with self.subTest(date=date):
                _, _, metadata = scraper.publication_evidence([post(date=date)], '333', AUTHOR)
                self.assertIsNone(metadata['created_at'])

    def test_conflicting_page_dates_restore_original_grid_order(self):
        items = [post(str(100+i), date=1700000000+i) for i in range(12)]
        profile_items = deepcopy(items)
        profile_items[-1]['createTime'] -= 1
        result, warnings, pages = self.process(items, profile_payloads=profile_items)
        self.assertEqual([item['id'] for item in result], [str(100+i) for i in range(10)])
        self.assertTrue(any('sin garantizar' in text for text in warnings))
        self.assertEqual(len(pages), 12)


class GridTests(unittest.TestCase):
    def test_supplied_grid_html_self_cards_photos_duplicates_and_foreign_links(self):
        with sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route('**/*', lambda route: route.abort())
                page.set_content('''
                    <aside><a href="https://www.tiktok.com/@other/video/999">Outside recommendation</a></aside>
                    <div data-e2e="user-post-item-list">
                        <div id="grid-item-container-0"><div data-e2e="user-post-item">
                            <a href="https://www.tiktok.com/@sofhotrositq/video/7698054054131272976"><div><picture>
                            <img alt="Descripción" src="https://fixture.invalid/thumb.jpg"></picture></div></a>
                        </div></div>
                        <a data-e2e="user-post-item" href="https://www.tiktok.com/@sofhotrositq/photo/333"><img></a>
                        <div data-e2e="user-post-item"><a href="https://www.tiktok.com/@sofhotrositq/photo/333">Duplicate</a></div>
                        <div data-e2e="user-post-item"><a href="https://www.tiktok.com/@other/photo/444">Foreign author</a></div>
                        <div data-e2e="user-post-item"><a href="https://foreign.invalid/@sofhotrositq/video/555">Foreign host</a></div>
                        <div data-e2e="user-post-item"><a href="http://www.tiktok.com/@sofhotrositq/video/666">HTTP</a></div>
                        <div data-e2e="user-post-item"><a href="https://www.tiktok.com/@sofhotrositq/video/bad">Invalid ID</a></div>
                        <a href="https://www.tiktok.com/@other/video/777">Inside grid but not a card</a>
                    </div>
                    <a data-e2e="user-post-item" href="https://www.tiktok.com/@other/photo/888">Card outside grid</a>
                ''')
                warnings = []
                result = scraper.get_profile_video_cards(page, username='sofhotrositq', warnings=warnings)
                self.assertEqual([(item['id'], item['type']) for item in result], [('7698054054131272976', 'video'), ('333', 'photo')])
                self.assertEqual(result[0]['url'], 'https://www.tiktok.com/@sofhotrositq/video/7698054054131272976')
                self.assertEqual(result[0]['preview_url'], 'https://fixture.invalid/thumb.jpg')
                self.assertTrue(any('444 descartada' in text for text in warnings))
            finally:
                browser.close()

    def test_missing_grid_does_not_fall_back_to_global_video_links(self):
        page = Mock(url='https://www.tiktok.com/@example')
        page.locator.return_value.first.wait_for.side_effect = scraper.PlaywrightTimeoutError('Missing grid')
        warnings = []
        with patch.object(scraper, 'validate_content_page'):
            result = scraper.get_profile_video_cards(page, username='example', warnings=warnings)
        self.assertEqual(result, [])
        self.assertTrue(any('no se usaron recomendaciones' in warning for warning in warnings))

    def test_profile_metrics_and_existing_session_configuration_are_unchanged(self):
        profile = sample_profile()
        context = Mock()
        context.new_page.return_value.goto.return_value.status = 200
        @contextmanager
        def persistent(**kwargs):
            self.assertEqual(kwargs, {'headless': True})
            yield context
        with patch.object(scraper, 'persistent_context', persistent), patch.object(scraper, 'validate_content_page'), patch.object(scraper, 'extract_profile_data', return_value=deepcopy(profile)), patch.object(scraper, 'extract_user_list', return_value=[]), patch.object(scraper, 'get_embedded_json', return_value=[]), patch.object(scraper, 'get_profile_video_cards', return_value=[]):
            result = scraper.scrape_profile('test_only')
        self.assertEqual([result[key] for key in ('followers', 'following', 'likes', 'bio')], [profile[key] for key in ('followers', 'following', 'likes', 'bio')])
        self.assertEqual(result['videos'], [])
        self.assertTrue(any('Resultado parcial: 0' in text for text in result['_meta']['warnings']))

    def test_captcha_after_loading_profile_returns_warning_without_global_fallback(self):
        context = Mock()
        context.new_page.return_value.goto.return_value.status = 200
        profile = sample_profile()
        @contextmanager
        def persistent(**kwargs):
            try:
                yield context
            finally:
                context.close()
        with patch.object(scraper, 'persistent_context', persistent), patch.object(scraper, 'validate_content_page', side_effect=[None, None, scraper.TikTokPageError('TikTok solicita verificación (CAPTCHA).')]), patch.object(scraper, 'extract_profile_data', return_value=deepcopy(profile)), patch.object(scraper, 'extract_user_list', return_value=[]), patch.object(scraper, 'get_profile_video_cards') as collect:
            result = scraper.scrape_profile('test_only')
        self.assertEqual(result['videos'], [])
        self.assertTrue(any('CAPTCHA' in text for text in result['_meta']['warnings']))
        collect.assert_not_called()
        context.new_page.assert_called_once()
        context.close.assert_called_once()
