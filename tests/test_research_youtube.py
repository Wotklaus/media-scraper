"""Controlled YouTube responses only. No API key, HTTP or external quota."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from pydantic import ValidationError
from backend.research_models import StudyCreate, StudyResponse
from backend.research_youtube import YouTubeConnector
from backend.research_sources import SourceFailure, source_capabilities
from backend.research_repository import ResearchRepository
from backend.research_worker import ResearchWorker
from research_fake import Database, Clock
from test_research import drain

VIDEO = 'abcdefghijk'


class Transport:
    def __init__(self, total=1100):
        self.total, self.calls = total, []

    def __call__(self, endpoint, params):
        self.calls.append((endpoint, params))
        if endpoint == 'search':
            return {'items': [{'id': {'videoId': VIDEO}}]}
        if endpoint == 'videos':
            return {'items': [{'id': VIDEO, 'snippet': {'title': 'Tema libre', 'description': 'Descripción @persona',
                'publishedAt': '2026-01-01T00:00:00Z'}, 'statistics': {'viewCount': '150'}}]}
        start = int(params.get('pageToken', '0'))
        end = min(start + params['maxResults'], self.total)
        items = []
        for index in range(start, end):
            # A repeated provider comment at the page boundary exercises real dedup semantics.
            identity = index - 1 if index == 50 else index
            comment = {'id': f'comment-{identity}', 'snippet': {'videoId': VIDEO,
                'textOriginal': f'Pregunta {identity} sobre el tema. persona@example.invalid @persona',
                'authorDisplayName': 'PRIVATE', 'authorChannelId': {'value': 'PRIVATE'},
                'publishedAt': '2026-01-01T00:00:00Z'}}
            items.append({'snippet': {'topLevelComment': comment, 'totalReplyCount': 0}})
        return {'items': items, **({'nextPageToken': str(end)} if end < self.total else {})}


class YouTubeTests(unittest.TestCase):
    def test_config_free_topics_and_capabilities(self):
        for topic in ('未知の研究', 'Tema inventado sin disciplina'):
            request = StudyCreate(topic=topic, source='youtube')
            self.assertEqual(request.source_config.max_publications, 20)
        for config in ({'publications': 20}, {'include_replies': 1}, {'max_publications': 201},
                       {'published_after': 'yesterday'}, {'published_after': '2026-01-01'},
                       {'published_after': '2026-02-01T00:00:00Z', 'published_before': '2026-01-01T00:00:00Z'}):
            with self.assertRaises(ValidationError):
                StudyCreate(topic='x', source='youtube', source_config=config)
        with patch.dict('os.environ', {'YOUTUBE_API_KEY': ''}):
            self.assertFalse(source_capabilities()[1]['available'])
        self.assertTrue(source_capabilities()[2]['available'])

    def test_discovery_metadata_and_search_pagination(self):
        calls = []
        def transport(endpoint, params):
            calls.append((endpoint, params))
            if endpoint == 'search':
                return {'items': [{'id': {'videoId': VIDEO}}], 'nextPageToken': 'second'}
            return Transport()(endpoint, params)
        connector = YouTubeConnector(transport)
        config = StudyCreate(topic='x', source='youtube', source_config={'max_publications': 2}).source_config.model_dump()
        page = connector.read(topic='consulta libre Ω', config=config, kind='discover', publication_id=None, cursor=None, limit=100, attempt=1)
        self.assertEqual(calls[0][1]['q'], 'consulta libre Ω')
        self.assertEqual(page.items[0]['metrics'], {'views': 150})
        second = connector.read(topic='consulta libre Ω', config=config, kind='discover', publication_id=None, cursor=page.next_cursor, limit=100, attempt=1)
        self.assertIsNone(second.next_cursor)
        self.assertEqual(calls[2][1]['pageToken'], 'second')

    def test_replies_pagination_and_return_to_threads(self):
        calls = []
        def transport(endpoint, params):
            calls.append((endpoint, params))
            comment = {'id': 'top', 'snippet': {'videoId': VIDEO, 'textOriginal': 'Pregunta'}}
            if endpoint == 'commentThreads':
                return {'items': [{'snippet': {'topLevelComment': comment, 'totalReplyCount': 2}}], 'nextPageToken': 'threads2'}
            return {'items': [{'id': 'reply', 'snippet': {'textOriginal': 'Respuesta'}}], **({'nextPageToken': 'reply2'} if 'pageToken' not in params else {})}
        connector = YouTubeConnector(transport)
        config = StudyCreate(topic='x', source='youtube', source_config={'include_replies': True}).source_config.model_dump()
        cursor = None
        pages = []
        for _ in range(4):
            page = connector.read(topic='x', config=config, kind='acquire', publication_id=VIDEO, cursor=cursor, limit=50, attempt=1)
            cursor = page.next_cursor; pages.append(page)
        self.assertEqual([call[0] for call in calls], ['commentThreads', 'comments', 'comments', 'commentThreads'])
        self.assertEqual(calls[-1][1]['pageToken'], 'threads2')
        self.assertEqual(pages[1].items[0]['record_kind'], 'reply')
        self.assertNotIn('authorDisplayName', str(pages))

    def test_http_errors_and_missing_key_are_sanitized(self):
        with patch.dict('os.environ', {'YOUTUBE_API_KEY': ''}), patch('backend.research_youtube.urlopen') as http:
            with self.assertRaises(SourceFailure) as caught:
                YouTubeConnector._http('search', {})
            self.assertEqual(caught.exception.code, 'credentials_missing'); http.assert_not_called()
        for status, reason, expected, retry in ((403, 'quotaExceeded', 'quota_exceeded', False),
                (403, 'commentsDisabled', 'comments_disabled', False), (429, 'rateLimitExceeded', 'provider_transient', True),
                (500, 'backendError', 'provider_transient', True), (403, 'keyInvalid', 'provider_access_denied', False)):
            error = HTTPError('https://private.invalid', status, 'SECRET', {}, io.BytesIO(json.dumps({'error': {'errors': [{'reason': reason}]}}).encode()))
            with patch.dict('os.environ', {'YOUTUBE_API_KEY': 'SECRET'}), patch('backend.research_youtube.urlopen', side_effect=error):
                with self.assertRaises(SourceFailure) as caught:
                    YouTubeConnector._http('search', {})
                self.assertEqual((caught.exception.code, caught.exception.retryable), (expected, retry))
                self.assertNotIn('SECRET', str(caught.exception))

    def test_malformed_and_wrong_provenance(self):
        config = StudyCreate(topic='x', source='youtube').source_config.model_dump()
        for result in ({}, {'items': [{'id': {'videoId': 'bad'}}]}, {'items': [], 'nextPageToken': 3}):
            with self.assertRaises(SourceFailure):
                YouTubeConnector(lambda *args: result).read(topic='x', config=config, kind='discover', publication_id=None, cursor=None, limit=50, attempt=1)

    def test_load_400_1000_recovery_privacy_and_response_models(self):
        for target in (400, 1000):
            with self.subTest(target=target):
                repo, clock = ResearchRepository(Database(), Clock()), None
                clock = repo.clock
                request = StudyCreate(topic='Cualquier tema Ω', source='youtube', target_records=target,
                    source_config={'max_pages_per_publication': 30})
                identity = repo.create(request)['study_id']; repo.control(identity, 'start')
                connector = YouTubeConnector(Transport())
                # Termination seam after durable staging. Resume must not call API for pending page.
                def crash(): raise SystemExit('controlled interruption')
                with self.assertRaises(SystemExit):
                    ResearchWorker(repo, connector, crash).tick()
                clock.advance(61)
                result = drain(repo, identity, clock, ResearchWorker(repo, connector))
                self.assertEqual(result['status'], 'target_reached')
                self.assertEqual(result['counters']['prepared'], target)
                self.assertEqual(result['counters']['duplicates'], 1)
                self.assertFalse(StudyResponse.model_validate(result).synthetic)
                rows = repo.record_page(identity)['records']
                self.assertTrue(all(not row['synthetic'] and row['source'] == 'youtube' for row in rows))
                self.assertNotIn('persona@example.invalid', str(rows))
                self.assertNotIn('PRIVATE', str(rows))
                self.assertEqual(repo.record_page(identity)['source_label'], 'YouTube Data API v3')


    def test_quota_pauses_and_explicit_resume_retries_same_cursor(self):
        clock = Clock(); repo = ResearchRepository(Database(), clock)
        identity = repo.create(StudyCreate(topic='libre', source='youtube', target_records=10))['study_id']
        repo.control(identity, 'start')
        class Blocked:
            def read(self, **kwargs): raise SourceFailure('quota_exceeded', False)
        ResearchWorker(repo, Blocked()).tick()
        self.assertEqual(repo.detail(identity)['status'], 'paused')
        self.assertEqual(repo.detail(identity)['last_error'], 'quota_exceeded')
        self.assertFalse(ResearchWorker(repo, Blocked()).tick())
        repo.control(identity, 'resume'); clock.advance(3)
        result = drain(repo, identity, clock, ResearchWorker(repo, YouTubeConnector(Transport())))
        self.assertEqual(result['counters']['prepared'], 10)

    def test_endpoints_no_credentials_and_controlled_acquisition(self):
        import asyncio
        from backend import research_routes
        from test_embeddings import request
        db = Database()
        with patch.object(research_routes, 'get_database', return_value=db):
            with patch.dict('os.environ', {'YOUTUBE_API_KEY': ''}):
                status, result = asyncio.run(request('POST', '/api/research/studies', body=b'{"topic":"free topic","source":"youtube"}'))
                self.assertEqual(status, 503)
                self.assertEqual(db['research_studies'].count_documents({}), 0)
            with patch.dict('os.environ', {'YOUTUBE_API_KEY': 'TEST-NEVER-SENT'}):
                status, result = asyncio.run(request('POST', '/api/research/studies', body=b'{"topic":"free topic","source":"youtube","target_records":10}'))
                self.assertEqual(status, 201); self.assertFalse(result['synthetic'])
                self.assertNotIn('TEST-NEVER-SENT', str(result))
                identity = result['study_id']
                asyncio.run(request('POST', f'/api/research/studies/{identity}/start'))
                repo = ResearchRepository(db)
                for _ in range(2): ResearchWorker(repo, YouTubeConnector(Transport())).tick()
                status, records = asyncio.run(request('GET', f'/api/research/studies/{identity}/records'))
                self.assertEqual(status, 200); self.assertEqual(records['total'], 10)
                self.assertFalse(records['records'][0]['synthetic'])


    def test_empty_source_and_configured_page_limit(self):
        config = StudyCreate(topic='x', source='youtube', source_config={'max_pages_per_publication': 1}).source_config.model_dump()
        page = YouTubeConnector(Transport()).read(topic='x', config=config, kind='acquire', publication_id=VIDEO, cursor=None, limit=50, attempt=1)
        self.assertEqual(len(page.items), 50); self.assertIsNone(page.next_cursor); self.assertTrue(page.truncated)
        page = YouTubeConnector(lambda *args: {'items': []}).read(topic='x', config=config, kind='discover', publication_id=None, cursor=None, limit=50, attempt=1)
        self.assertEqual(page.items, []); self.assertIsNone(page.next_cursor)

    def test_successful_http_uses_header_and_bounded_body(self):
        from unittest.mock import MagicMock
        response = MagicMock(); response.__enter__.return_value.read.return_value = b'{"items":[]}'
        with patch.dict('os.environ', {'YOUTUBE_API_KEY': 'TEST-SECRET'}), patch('backend.research_youtube.urlopen', return_value=response) as http:
            self.assertEqual(YouTubeConnector._http('search', {'q': 'tema Ω'}), {'items': []})
            outgoing = http.call_args.args[0]
            self.assertNotIn('TEST-SECRET', outgoing.full_url)
            self.assertEqual(outgoing.get_header('X-goog-api-key'), 'TEST-SECRET')
            self.assertEqual(http.call_args.kwargs['timeout'], 10)
        with patch.dict('os.environ', {'YOUTUBE_API_KEY': 'TEST-SECRET'}), patch('backend.research_youtube.urlopen', side_effect=URLError('SECRET')):
            with self.assertRaises(SourceFailure) as caught:
                YouTubeConnector._http('search', {})
            self.assertTrue(caught.exception.retryable)


    def test_capped_publication_is_not_reported_as_complete(self):
        clock = Clock(); repo = ResearchRepository(Database(), clock)
        identity = repo.create(StudyCreate(topic='x', source='youtube', target_records=400,
            source_config={'max_pages_per_publication': 1}))['study_id']
        repo.control(identity, 'start')
        result = drain(repo, identity, clock, ResearchWorker(repo, YouTubeConnector(Transport())))
        self.assertEqual(result['status'], 'exhausted')
        self.assertFalse(repo.publication_page(identity)['publications'][0]['source_complete'])
