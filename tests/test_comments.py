"""Synthetic comment fixtures only; these do not establish TikTok's real DOM."""
import unittest
from unittest.mock import Mock, patch

from playwright.sync_api import sync_playwright
from backend import scraper


class CommentDOMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.route('**/*', lambda route: route.abort())
        self.addCleanup(self.page.close)

    def extract(self, html, limit=10):
        self.page.set_content(html)
        warnings = []
        result = scraper._extract_dom_comments(self.page, limit=limit, warnings=warnings)
        return result, warnings

    def test_both_existing_selectors_unicode_duplicates_and_limit(self):
        html = '<div data-e2e="comment-level-1"><a href="/@first">First</a><p data-e2e="comment-text">Hola ñ 🎵</p></div>'
        html += '<div data-e2e="comment-item"><a href="/@FIRST">First</a><p data-e2e="comment-content">Hola ñ 🎵</p></div>'
        html += ''.join(f'<div data-e2e="comment-item"><a href="/@reader{i}">Reader</a><p data-e2e="comment-text">Text {i}</p></div>' for i in range(15))
        result, warnings = self.extract(html, limit=50)
        self.assertEqual(len(result), 10)
        self.assertEqual(result[0], {'username': 'first', 'text': 'Hola ñ 🎵'})
        self.assertEqual(result[1]['username'], 'reader0')
        self.assertEqual(warnings, [])
        self.assertEqual(scraper.read_comment_text(scraper.find_comment_items(self.page).first), 'Hola ñ 🎵')

    def test_nested_reply_does_not_supply_parent_author_or_text(self):
        result, warnings = self.extract('''<div data-e2e="comment-level-1">
            <div data-e2e="comment-item"><a href="/@reply">Reply</a>
            <p data-e2e="comment-text">Real reply</p></div></div>''')
        self.assertEqual(result, [{'username': 'reply', 'text': 'Real reply'}])
        self.assertTrue(any('sin autor o texto' in message for message in warnings))

    def test_hidden_and_invalid_elements_do_not_become_comments(self):
        result, warnings = self.extract('''
            <div data-e2e="comment-item" style="display:none"><a href="/@hidden">H</a><p data-e2e="comment-text">Hidden</p></div>
            <div data-e2e="comment-item"><a href="https://foreign.invalid/@fake">Fake</a><p data-e2e="comment-text">Wrong host</p></div>
            <div data-e2e="comment-item"><a href="/@valid">Valid</a><p data-e2e="comment-content">Available</p></div>''')
        self.assertEqual(result, [{'username': 'valid', 'text': 'Available'}])
        self.assertTrue(warnings)

    def test_delayed_comments_are_read_within_existing_budget(self):
        self.page.set_content('''<script>setTimeout(() => {
            document.body.innerHTML = '<div data-e2e="comment-item"><a href="/@reader">R</a><p data-e2e="comment-text">Loaded</p></div>';
        }, 100)</script>''')
        self.assertEqual(scraper._extract_dom_comments(self.page), [{'username': 'reader', 'text': 'Loaded'}])

    def test_browser_response_event_before_navigation_and_panel(self):
        import json
        payload = {'status_code': 0, 'total': 1, 'cursor': 0, 'has_more': 0,
                   'comments': [{'cid': '123', 'text': 'Synthetic network',
                                 'user': {'unique_id': 'reader'}}]}
        html = """<button data-e2e="comment-icon" onclick="fetch('/api/comment/list/?aweme_id=222')">Comments</button>"""
        def route_request(route):
            if '/api/comment/list/' in route.request.url:
                route.fulfill(content_type='application/json', body=json.dumps(payload))
            else:
                route.fulfill(content_type='text/html', body=html)
        self.page.route('**/*', route_request)
        capture = scraper.CommentResponseCapture('222')
        self.page.on('response', capture.on_response)
        try:
            self.page.goto('https://www.tiktok.com/@example/video/222')
            result = scraper.extract_video_comments(self.page, capture=capture)
            self.assertEqual(result, [{'username': 'reader', 'text': 'Synthetic network', 'cid': '123'}])
            self.assertEqual(capture.issues, [])
        finally:
            self.page.remove_listener('response', capture.on_response)

    def test_late_button_is_awaited_and_panel_is_confirmed(self):
        self.page.set_content('''<script>setTimeout(() => {
            const button = document.createElement('button');
            button.dataset.e2e = 'comment-icon'; button.textContent = 'Comments';
            button.onclick = () => document.body.insertAdjacentHTML('beforeend',
                '<div data-e2e="comment-item"><a href="/@reader">R</a><p data-e2e="comment-text">Late button</p></div>');
            document.body.appendChild(button);
        }, 150)</script>''')
        warnings = []
        with self.assertLogs('backend.scraper', level='DEBUG') as logs:
            result = scraper.extract_video_comments(self.page, warnings=warnings)
        self.assertEqual(result, [{'username': 'reader', 'text': 'Late button'}])
        self.assertEqual(warnings, [])
        self.assertTrue(any('panel=visible' in line for line in logs.output))



class CommentFailureTests(unittest.TestCase):
    def page(self):
        page = Mock(url='https://www.tiktok.com/@example/video/222')
        page.locator.return_value.first.wait_for.side_effect = scraper.PlaywrightTimeoutError('synthetic timeout')
        return page

    @patch.object(scraper, 'validate_content_page')
    def test_missing_dom_positive_or_unknown_count_is_not_claimed_empty(self, validate):
        for count in (18, None):
            page = self.page()
            warnings = []
            self.assertEqual(scraper._extract_dom_comments(page, warnings=warnings, expected_count=count), [])
            self.assertIn('No se puede confirmar una lista vacía', warnings[0])
            page.locator.return_value.first.wait_for.assert_called_once_with(state='attached', timeout=3000)

    @patch.object(scraper, 'validate_content_page')
    def test_zero_count_and_no_dom_needs_no_failure_warning(self, validate):
        warnings = []
        self.assertEqual(scraper._extract_dom_comments(self.page(), warnings=warnings, expected_count=0), [])
        self.assertEqual(warnings, [])

    @patch.object(scraper, 'validate_content_page', side_effect=scraper.TikTokPageError('CAPTCHA'))
    def test_gate_is_reported_without_interaction(self, validate):
        page = self.page()
        warnings = []
        self.assertEqual(scraper._extract_dom_comments(page, warnings=warnings), [])
        self.assertIn('CAPTCHA', warnings[0])
        page.locator.assert_not_called()

    @patch.object(scraper, 'validate_content_page')
    def test_dom_read_failure_is_reported_and_does_not_escape(self, validate):
        page = self.page()
        page.locator.return_value.first.wait_for.side_effect = None
        page.locator.return_value.evaluate_all.side_effect = scraper.PlaywrightError('detached')
        warnings = []
        self.assertEqual(scraper._extract_dom_comments(page, warnings=warnings), [])
        self.assertIn('falló la lectura', warnings[0])

    def test_zero_limit_does_not_touch_page(self):
        page = Mock()
        self.assertEqual(scraper._extract_dom_comments(page, limit=0), [])
        page.locator.assert_not_called()


class CommentResponseTests(unittest.TestCase):
    def entry(self, cid='1', **changes):
        return {'cid': cid, 'text': 'Hola 🎵', 'user': {'unique_id': 'reader'},
                'create_time': 1700000000, 'digg_count': 0,
                'reply_comment_total': 2, 'comment_language': 'es', **changes}

    def response(self, entries=None, publication='222', **changes):
        data = {'status_code': 0, 'comments': [self.entry()] if entries is None else entries,
                'total': 18, 'cursor': 0, 'has_more': 1, **changes}
        return Mock(url=f'https://www.tiktok.com/api/comment/list/?aweme_id={publication}',
                    status=200, json=Mock(return_value=data))

    def test_valid_fields_and_cid_deduplication_across_responses(self):
        capture = scraper.CommentResponseCapture('222')
        capture.on_response(self.response())
        capture.on_response(self.response())
        capture.on_response(self.response([self.entry('2')]))
        self.assertEqual(len(capture.comments), 2)
        self.assertEqual(capture.comments[0], {
            'username': 'reader', 'text': 'Hola 🎵', 'cid': '1',
            'create_time': 1700000000, 'digg_count': 0,
            'reply_comment_total': 2, 'comment_language': 'es'})
        self.assertEqual(capture.issues, [])

    def test_hard_limit_and_text_fallback_deduplication(self):
        capture = scraper.CommentResponseCapture('222')
        capture.on_response(self.response([self.entry(str(i)) for i in range(30)]))
        self.assertEqual(len(capture.comments), 10)
        capture = scraper.CommentResponseCapture('222')
        capture.on_response(self.response([self.entry(cid=None), self.entry(cid=None)]))
        self.assertEqual(len(capture.comments), 1)

    def test_verified_empty_and_unavailable_are_distinct(self):
        capture = scraper.CommentResponseCapture('222')
        capture.on_response(self.response([], total=0, has_more=0))
        self.assertTrue(capture.empty)
        self.assertEqual(capture.issues, [])
        capture = scraper.CommentResponseCapture('222')
        capture.on_response(self.response([]))
        self.assertFalse(capture.empty)
        self.assertIn('no disponibles', capture.issues[0])

    def test_wrong_post_host_endpoint_and_ambiguous_id_are_rejected(self):
        for url in ('https://www.tiktok.com/api/comment/list/?aweme_id=999',
                    'https://foreign.invalid/api/comment/list/?aweme_id=222',
                    'https://www.tiktok.com/api/comment/list/reply/?aweme_id=222',
                    'https://www.tiktok.com/api/comment/list/',
                    'https://www.tiktok.com/api/comment/list/?aweme_id=222&aweme_id=999'):
            with self.subTest(url=url):
                capture = scraper.CommentResponseCapture('222')
                response = self.response()
                response.url = url
                capture.on_response(response)
                self.assertEqual(capture.comments, [])
                response.json.assert_not_called()
                if 'foreign' not in url and 'reply' not in url and 'aweme_id=999' != url.split('?')[-1]:
                    self.assertTrue(capture.issues)

    def test_contradictory_response_and_entry_identifiers_are_rejected(self):
        for response in (self.response(aweme_id='999'),
                         self.response([self.entry(aweme_id='999')])):
            capture = scraper.CommentResponseCapture('222')
            capture.on_response(response)
            self.assertEqual(capture.comments, [])
            self.assertTrue(capture.issues)

    def test_malformed_unsuccessful_or_unreadable_json(self):
        responses = [self.response(comments=None), self.response(status_code=1),
                     self.response(total='18'), self.response(cursor=-1), self.response(has_more=2)]
        for data in ([], None, 'invalid'):
            response = self.response()
            response.json.return_value = data
            responses.append(response)
        response = self.response()
        response.json.side_effect = ValueError('invalid json')
        responses.append(response)
        response = self.response()
        response.status = 403
        responses.append(response)
        for response in responses:
            capture = scraper.CommentResponseCapture('222')
            capture.on_response(response)
            self.assertFalse(capture.empty)
            self.assertEqual(capture.comments, [])
            self.assertTrue(capture.issues)

    def test_invalid_authors_text_and_optional_fields(self):
        capture = scraper.CommentResponseCapture('222')
        capture.on_response(self.response([None, self.entry(user={'nickname': 'Display name'}),
                                          self.entry(text=' '), self.entry(user={'unique_id': 'a', 'uniqueId': 'b'}),
                                          self.entry(digg_count=True, create_time='unknown', reply_comment_total=-1)]))
        self.assertEqual(len(capture.comments), 1)
        self.assertNotIn('digg_count', capture.comments[0])
        self.assertNotIn('create_time', capture.comments[0])
        self.assertTrue(capture.issues)

    @patch.object(scraper, 'validate_content_page')
    @patch.object(scraper, '_extract_dom_comments')
    def test_network_preferred_and_valid_empty_skips_dom(self, dom, validate):
        for response in (self.response(), self.response([], total=0, has_more=0)):
            capture = scraper.CommentResponseCapture('222')
            capture.on_response(response)
            page = Mock()
            self.assertEqual(scraper.extract_video_comments(page, capture=capture), capture.comments)
            dom.assert_not_called()
            page.request.get.assert_not_called()

    @patch.object(scraper, 'validate_content_page')
    @patch.object(scraper, '_extract_dom_comments', return_value=[{'username': 'reader', 'text': 'DOM'}])
    def test_dom_fallback_listener_lifecycle_and_warnings(self, dom, validate):
        page = Mock(url='https://www.tiktok.com/@example/video/222')
        page.locator.return_value.first.count.return_value = 0
        page.locator.return_value.count.return_value = 1
        warnings = []
        result = scraper.extract_video_comments(page, warnings=warnings)
        self.assertEqual(result, dom.return_value)
        page.on.assert_called_once()
        page.remove_listener.assert_called_once_with(*page.on.call_args.args)
        self.assertLessEqual(dom.call_args.kwargs['timeout'], 3000)
        page.request.get.assert_not_called()


class CommentCoordinationTests(unittest.TestCase):
    def page(self):
        page = Mock(url='https://www.tiktok.com/@example/video/222')
        page.locator.return_value.count.return_value = 1
        return page

    @patch.object(scraper, 'validate_content_page')
    @patch.object(scraper, '_extract_dom_comments', return_value=[])
    def test_click_failure_is_distinct_and_never_forced(self, dom, validate):
        page = self.page()
        # Hidden panel before click, then a visible container ends the wait.
        page.locator.return_value.count.side_effect = [0, 1]
        page.locator.return_value.first.click.side_effect = scraper.PlaywrightTimeoutError('sensitive URL must not be logged')
        warnings = []
        scraper.extract_video_comments(page, warnings=warnings)
        self.assertTrue(any('Falló el clic' in text for text in warnings))
        self.assertFalse(any('sensitive' in text for text in warnings))
        page.locator.return_value.first.click.assert_called_once_with(trial=True, timeout=500)

    @patch.object(scraper, 'validate_content_page')
    @patch.object(scraper, '_extract_dom_comments', return_value=[])
    def test_button_unavailable_warning(self, dom, validate):
        page = self.page()
        page.locator.return_value.count.side_effect = [0, 1]
        page.locator.return_value.first.wait_for.side_effect = scraper.PlaywrightTimeoutError('missing')
        warnings = []
        scraper.extract_video_comments(page, warnings=warnings)
        self.assertTrue(any('no apareció visible' in text for text in warnings))
        page.locator.return_value.first.click.assert_not_called()
        page.locator.return_value.first.wait_for.assert_called_once_with(state='visible', timeout=1200)

    @patch.object(scraper, 'validate_content_page')
    def test_response_during_dom_fallback_wins_and_drops_stale_warning(self, validate):
        page = self.page()
        capture = scraper.CommentResponseCapture('222')
        def fallback(*args, **kwargs):
            args[2].append('stale DOM warning')
            capture.on_response(CommentResponseTests().response())
            return []
        warnings = []
        with patch.object(scraper, '_extract_dom_comments', side_effect=fallback):
            result = scraper.extract_video_comments(page, warnings=warnings, capture=capture)
        self.assertEqual(result, capture.comments)
        self.assertEqual(result[0]['cid'], '1')
        self.assertEqual(warnings, [])

    @patch.object(scraper, 'validate_content_page')
    @patch.object(scraper, '_extract_dom_comments', return_value=[])
    @patch.object(scraper, 'monotonic', side_effect=[0, .1, .2, .3, 3.1, 3.1])
    def test_completed_click_without_loaded_comments_is_reported(self, clock, dom, validate):
        page = self.page()
        page.locator.return_value.count.return_value = 0
        warnings = []
        scraper.extract_video_comments(page, warnings=warnings)
        self.assertTrue(any('El clic se completó' in text for text in warnings))
        self.assertEqual(page.locator.return_value.first.click.call_count, 2)
        self.assertEqual(dom.call_args.kwargs['timeout'], 1)

    def test_safe_diagnostics_and_isolation(self):
        first = scraper.CommentResponseCapture('222')
        second = scraper.CommentResponseCapture('999')
        response = CommentResponseTests().response()
        response.url += '&token=SECRET'
        for capture in (first, second):
            capture.on_response(response)
        self.assertEqual(len(first.comments), 1)
        self.assertEqual(second.comments, [])
        self.assertEqual(first.diagnostics['matched_publication'], 1)
        self.assertEqual(second.diagnostics['other_publication'], 1)
        self.assertNotIn('SECRET', repr(first.diagnostics))
        for url, reason in (
            ('https://foreign.invalid/api/comment/list/?aweme_id=222', 'discard_host'),
            ('https://www.tiktok.com/api/comment/list/reply/?aweme_id=222', 'discard_path'),
            ('https://www.tiktok.com/api/comment/list/', 'discard_aweme_id'),
        ):
            response.url = url
            first.on_response(response)
            self.assertEqual(first.diagnostics[reason], 1)
        response = CommentResponseTests().response(status_code=1)
        first.on_response(response)
        self.assertEqual(first.diagnostics['discard_structure'], 1)
        response.status = 403
        first.on_response(response)
        self.assertEqual(first.diagnostics['discard_http'], 1)
