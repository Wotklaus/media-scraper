import unittest
from unittest.mock import Mock, patch

from backend import scraper


URL = 'https://www.tiktok.com/@example/video/222'


def video(video_id='222', **stats):
    return {'id': video_id, 'desc': 'Requested video',
            'stats': stats or {'playCount': 2000}, 'video': {'cover': 'cover.jpg'}}


def page_with_scripts(*contents):
    page = Mock()
    page.url = URL
    scripts = Mock()
    scripts.all.return_value = [Mock(text_content=Mock(return_value=c)) for c in contents]
    page.locator.return_value = scripts
    return page


def content_page(url=URL, screen=None, message=None):
    page = Mock()
    page.url = url
    def locate(selector):
        elements = [Mock(is_visible=Mock(return_value=True))] if screen and screen in selector else []
        return Mock(all=Mock(return_value=elements))
    page.locator.side_effect = locate
    page.get_by_text.side_effect = lambda text, **kw: Mock(
        all=Mock(return_value=[Mock(is_visible=Mock(return_value=True))] if text == message else []))
    return page


class EmbeddedJSONTests(unittest.TestCase):
    def test_reads_all_blocks_and_skips_invalid_and_empty(self):
        page = page_with_scripts('{"unrelated": true}', '{broken', '',
                                 '{"itemStruct":{"id":"222","stats":{"playCount":2000}}}')
        payloads = scraper.get_embedded_json(page)
        self.assertEqual(len(payloads), 2)
        self.assertEqual(scraper.find_video_payload(payloads, '222')['stats']['playCount'], 2000)

    def test_absent_scripts(self):
        page = page_with_scripts()
        page.locator.return_value.first.wait_for.side_effect = scraper.PlaywrightTimeoutError('missing')
        self.assertEqual(scraper.get_embedded_json(page), [])


class VideoPayloadTests(unittest.TestCase):
    def test_ignores_recommendations_before_requested_video(self):
        requested = video()
        data = {'recommendations': [video('111')], 'detail': {'itemStruct': requested}}
        self.assertIs(scraper.find_video_payload(data, '222'), requested)

    def test_missing_id_and_other_ids_never_match(self):
        self.assertIsNone(scraper.find_video_payload(
            [{'stats': {'playCount': 999}}, video('111')], '222'))

    def test_numeric_id_and_zero_metrics(self):
        requested = video(222, playCount=0)
        self.assertIs(scraper.find_video_payload({'ItemModule': {'222': requested}}, '222'), requested)

    def test_ignores_matching_objects_without_metrics(self):
        requested = video()
        self.assertIs(scraper.find_video_payload(
            [{'id': '222', 'stats': {}}, requested], '222'), requested)


class ContentPageTests(unittest.TestCase):
    def test_normal_page_is_accepted(self):
        scraper.validate_content_page(content_page())

    def test_access_redirects(self):
        for path in ('login', 'signup', 'captcha', 'verify', 'challenge'):
            with self.subTest(path=path), self.assertRaises(scraper.TikTokPageError):
                scraper.validate_content_page(content_page('https://www.tiktok.com/' + path))

    def test_visible_access_screens(self):
        for screen in ('captcha', 'login-modal', 'video-unavailable', 'user-not-found'):
            with self.subTest(screen=screen), self.assertRaises(scraper.TikTokPageError):
                scraper.validate_content_page(content_page(screen=screen))

    def test_unavailable_message(self):
        with self.assertRaises(scraper.TikTokPageError):
            scraper.validate_content_page(content_page(message='Video currently unavailable'))

    def test_hidden_gate_is_not_a_block(self):
        page = content_page()
        page.locator.side_effect = None
        page.locator.return_value.all.return_value = [Mock(is_visible=Mock(return_value=False))]
        scraper.validate_content_page(page)


class ExtractionTests(unittest.TestCase):
    @patch.object(scraper, 'extract_video_comments', return_value=[{'username': 'reader', 'text': 'Hi'}])
    @patch.object(scraper, 'get_embedded_json')
    def test_metrics_and_response_fields_are_preserved(self, embedded, comments):
        embedded.return_value = [video('111', playCount=999999), video(
            playCount=2000, diggCount=0, commentCount=3, shareCount=4, collectCount=5)]
        result = scraper.extract_video_details(content_page(), URL)
        self.assertEqual(set(result), {'url', 'preview_url', 'title', 'views', 'likes',
                                      'comments', 'shares', 'saves', 'comments_list'})
        self.assertEqual([result[k] for k in ('views', 'likes', 'comments', 'shares', 'saves')],
                         ['2.0K', '0', '3', '4', '5'])
        self.assertEqual(result['comments_list'], comments.return_value)

    @patch.object(scraper, 'extract_video_comments', return_value=[{'username': 'reader', 'text': 'Hi'}])
    @patch.object(scraper, 'get_embedded_json', return_value=[video('111')])
    def test_missing_metrics_preserves_comments_without_using_recommendations(self, embedded, comments):
        with patch('builtins.print') as diagnostic:
            result = scraper.extract_video_details(content_page(), URL)
        self.assertEqual(result['views'], 'N/A')
        self.assertEqual(result['comments_list'], comments.return_value)
        self.assertIn('requested metrics are missing', diagnostic.call_args.args[0])

    def test_blocked_video_preserves_card_fields_and_closes_page(self):
        page = content_page('https://www.tiktok.com/login')
        page.goto.return_value = Mock(status=200)
        context = Mock(new_page=Mock(return_value=page))
        result = scraper.extract_latest_videos(context, [{'id': '222', 'url': URL}])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '222')
        self.assertEqual(result[0]['views'], 'N/A')
        self.assertEqual(result[0]['comments_list'], [])
        page.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
