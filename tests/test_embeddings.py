"""Offline tests: all MongoDB and OpenAI access is simulated."""

import asyncio
from copy import deepcopy
from datetime import timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pymongo.errors import DuplicateKeyError

from backend import embedding_routes, embeddings, main
from backend.embedding_repository import EmbeddingRepository


class Cursor(list):
    def sort(self, *args):
        return self

    def limit(self, limit):
        return Cursor(self[:limit])


class Collection:
    def __init__(self, rows=()):
        self.rows = deepcopy(list(rows))
        self.create_index = Mock()

    def find(self, query, projection=None):
        rows = [row for row in self.rows if all(row.get(k) == v for k, v in query.items())]
        if projection and any(projection.values()):
            rows = [{k: v for k, v in row.items() if projection.get(k)} for row in rows]
        return Cursor(deepcopy(rows))

    def find_one(self, query, projection=None):
        rows = self.find(query, projection)
        return rows[0] if rows else None

    def update_one(self, identity, update, upsert=False):
        if self.find_one(identity):
            return SimpleNamespace(upserted_id=None)
        self.rows.append(deepcopy(update['$setOnInsert']))
        return SimpleNamespace(upserted_id='new-id')


def fixture(count=2):
    database = {
        'profiles': Collection([{'username': 'TestUser', 'username_key': 'testuser'}]),
        'publications': Collection([{'publication_id': str(100 + i),
            'profile_username': 'TestUser', 'description': f'Descripción {i} 🎵',
            'metrics': {'likes': 30}} for i in range(count)]),
        'embeddings': Collection(),
    }
    database['publications'].rows.append({'publication_id': 'other',
        'profile_username': 'Other', 'description': 'Do not send'})
    client = Mock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[1.0] + [0.0] * 1535)])
    factory = Mock(return_value=client)
    repo = EmbeddingRepository(database)
    return database, client, factory, embeddings.EmbeddingService(repo, factory)


async def request(method, path, query=b'', body=b''):
    events = []
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
             'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
             'query_string': query, 'headers': [(b'content-type', b'application/json')] if body else [], 'client': ('127.0.0.1', 123),
             'server': ('127.0.0.1', 8000), 'root_path': ''}
    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}
    async def send(event):
        events.append(event)
    await asyncio.wait_for(main.app(scope, receive, send), timeout=5)
    return (next(e['status'] for e in events if e['type'] == 'http.response.start'),
            json.loads(b''.join(e.get('body', b'') for e in events)))


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.db, self.client, self.factory, self.service = fixture()

    def test_generation_stores_schema_and_only_sends_text(self):
        before = deepcopy(self.db['publications'].rows)
        result = self.service.generate('@TESTUSER')
        self.assertEqual((result['generated'], result['reused'], result['failed']), (2, 0, 0))
        doc = self.db['embeddings'].rows[0]
        self.assertEqual(set(doc), {'publication_id', 'profile_username', 'text', 'model',
                                   'vector', 'content_hash', 'generated_at'})
        self.assertEqual(len(doc['vector']), 1536)
        self.assertEqual(len(doc['content_hash']), 64)
        self.assertEqual(doc['generated_at'].tzinfo, timezone.utc)
        self.client.embeddings.create.assert_any_call(model=embeddings.MODEL,
            input='Descripción 0 🎵', dimensions=1536, encoding_format='float')
        self.assertEqual(self.db['publications'].rows, before)
        self.client.close.assert_called_once()

    def test_duplicate_reuses_without_client_or_timestamp_changes(self):
        self.service.generate('testuser')
        before = deepcopy(self.db['embeddings'].rows)
        self.factory.reset_mock()
        result = self.service.generate('testuser')
        self.assertEqual((result['generated'], result['reused']), (0, 2))
        self.factory.assert_not_called()
        self.assertEqual(before, self.db['embeddings'].rows)

    def test_changed_text_or_model_requires_new_embedding(self):
        self.service.generate('testuser')
        self.db['publications'].rows[0]['description'] = 'Nuevo texto'
        self.db['embeddings'].rows[1]['model'] = 'previous-model'
        self.assertEqual(self.service.generate('testuser')['generated'], 2)
        self.assertEqual(len(self.db['embeddings'].rows), 4)

    def test_whitespace_is_normalized_for_hash_and_input(self):
        self.service.generate('testuser')
        self.db['publications'].rows[0]['description'] = '  Descripción 0 🎵\n'
        self.assertEqual(self.service.generate('testuser')['reused'], 2)

    def test_empty_missing_and_nontext_are_skipped_without_client(self):
        for value in (None, '', ' \n ', 12):
            with self.subTest(value=value):
                for row in self.db['publications'].rows:
                    row['description'] = value
                result = self.service.generate('testuser')
                self.assertEqual((result['skipped'], result['failed']), (2, 0))
        self.factory.assert_not_called()

    def test_maximum_ten_and_smaller_explicit_limit(self):
        db, client, factory, service = fixture(15)
        self.assertEqual(service.generate('testuser')['processed'], 10)
        self.assertEqual(client.embeddings.create.call_count, 10)
        self.assertEqual(service.list('testuser', 3)['count'], 3)
        self.assertEqual(service.generate('testuser', 2)['processed'], 2)
        for limit in (0, 11, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                service.generate('testuser', limit)

    def test_unknown_profile_and_no_publications(self):
        with self.assertRaises(LookupError):
            self.service.generate('missing')
        self.db['publications'].rows.clear()
        self.assertEqual(self.service.generate('testuser')['processed'], 0)
        self.factory.assert_not_called()

    def test_openai_failure_is_safe_and_remaining_items_continue(self):
        good = self.client.embeddings.create.return_value
        self.client.embeddings.create.side_effect = [RuntimeError('secret-key'), good]
        result = self.service.generate('testuser')
        self.assertEqual((result['generated'], result['failed']), (1, 1))
        self.assertNotIn('secret-key', json.dumps(result))

    def test_client_configuration_failure_is_safe(self):
        self.factory.side_effect = RuntimeError('secret-key')
        result = self.service.generate('testuser')
        self.assertEqual(result['failed'], 2)
        self.assertNotIn('secret-key', json.dumps(result))

    def test_invalid_vectors_are_never_saved(self):
        for vector in ([1.0], [0.0] * 1536, [float('nan')] * 1536,
                       [float('inf')] * 1536, ['invalid'] * 1536):
            with self.subTest(value=vector[0]):
                self.client.embeddings.create.return_value.data[0].embedding = vector
                self.assertEqual(self.service.generate('testuser')['failed'], 2)
                self.assertEqual(self.db['embeddings'].rows, [])

    def test_mongodb_failure_is_counted_without_details(self):
        with patch.object(self.service.repository, 'save', side_effect=RuntimeError('mongodb-secret')):
            result = self.service.generate('testuser')
        self.assertEqual(result['failed'], 2)
        self.assertNotIn('mongodb-secret', json.dumps(result))

    def test_unique_index_and_atomic_insert_only_upsert(self):
        self.service.generate('testuser')
        self.db['embeddings'].create_index.assert_any_call(
            [('publication_id', 1), ('model', 1), ('content_hash', 1)],
            unique=True, name='publication_model_content_unique')
        doc = self.db['embeddings'].rows[0]
        identity = {k: doc[k] for k in ('publication_id', 'model', 'content_hash')}
        self.assertFalse(self.service.repository.save(identity, {**doc, 'text': 'do not overwrite'}))
        self.assertEqual(self.db['embeddings'].rows[0]['text'], doc['text'])
        with patch.object(self.db['embeddings'], 'update_one', side_effect=DuplicateKeyError('race')):
            self.assertFalse(self.service.repository.save(identity, doc))

    def test_get_does_not_generate_or_create_indexes(self):
        self.assertEqual(self.service.list('testuser')['embeddings'], [])
        self.factory.assert_not_called()
        self.db['embeddings'].create_index.assert_not_called()

    def test_construction_and_profile_query_do_not_generate(self):
        with patch.object(embeddings, 'OpenAI') as sdk, patch.object(embedding_routes, 'get_database') as connect:
            embeddings.EmbeddingService(EmbeddingRepository(self.db))
            profile = {'username': 'TestUser', 'videos': []}
            with patch.object(main, 'scrape_profile', return_value=profile), \
                    patch.object(main, 'save_profile'), patch.object(main, 'print_profile'):
                self.assertEqual(main.get_profile('TestUser'), profile)
            sdk.assert_not_called()
            connect.assert_not_called()

    def test_similarity_uses_current_descriptions_and_never_generates(self):
        self.service.generate('testuser')
        self.factory.reset_mock()
        self.assertAlmostEqual(self.service.similarity('testuser', '100', '101')['similarity'], 1)
        self.db['publications'].rows[0]['description'] = 'Changed'
        with self.assertRaises(LookupError):
            self.service.similarity('testuser', '100', '101')
        with self.assertRaises(LookupError):
            self.service.similarity('testuser', 'other', '101')
        self.factory.assert_not_called()

    def test_cosine_known_values(self):
        for a, b, expected in (([1, 0], [1, 0], 1), ([1, 0], [0, 1], 0),
                                ([1, 0], [-1, 0], -1), ([2, 2], [4, 4], 1)):
            self.assertAlmostEqual(embeddings.cosine_similarity(a, b), expected)

    def test_cosine_invalid_values(self):
        for a, b in (([], []), ([0], [1]), ([1], [1, 2]), ([float('nan')], [1]),
                     ([float('inf')], [1]), ([True], [1]), (['x'], [1])):
            with self.subTest(a=a), self.assertRaises(ValueError):
                embeddings.cosine_similarity(a, b)

    def test_key_loaded_from_env_file_and_retries_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env'
            path.write_text('# Test only\nOPENAI_API_KEY="synthetic-key"\n')
            with patch.object(embeddings, 'ENV_FILE', path), patch.object(embeddings, 'OpenAI') as sdk:
                embeddings.create_openai_client()
                sdk.assert_called_once_with(api_key='synthetic-key', max_retries=0, timeout=30.0)
            path.write_text('OTHER=value\n')
            with patch.object(embeddings, 'ENV_FILE', path), self.assertRaises(RuntimeError):
                embeddings.create_openai_client()


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.db, self.client, self.factory, self.service = fixture()
        main.app.dependency_overrides[embedding_routes.embedding_service] = lambda: self.service
        self.scrape = patch.object(main, 'scrape_profile', side_effect=AssertionError('Scraper forbidden'))
        self.scrape.start()

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.scrape.stop()

    def test_post_get_and_similarity_routes(self):
        status, result = asyncio.run(request('POST', '/api/embeddings/testuser'))
        self.assertEqual((status, result['generated']), (200, 2))
        status, result = asyncio.run(request('GET', '/api/embeddings/testuser'))
        self.assertEqual((status, result['count']), (200, 2))
        self.assertIsInstance(result['embeddings'][0]['generated_at'], str)
        status, result = asyncio.run(request('GET', '/api/embeddings/testuser/similarity',
                                             b'first_id=100&second_id=101'))
        self.assertEqual((status, result['similarity']), (200, 1.0))
        self.assertEqual(self.client.embeddings.create.call_count, 2)

    def test_get_and_invalid_limits_make_no_calls(self):
        status, _ = asyncio.run(request('GET', '/api/embeddings/testuser'))
        self.assertEqual(status, 200)
        for method in ('POST', 'GET'):
            for query in (b'limit=11', b'limit=0', b'limit=invalid'):
                status, _ = asyncio.run(request(method, '/api/embeddings/testuser', query))
                self.assertEqual(status, 422)
        self.factory.assert_not_called()

    def test_real_dependency_maps_errors_and_closes_database(self):
        main.app.dependency_overrides.clear()
        db = Mock()
        db.__getitem__ = Mock(side_effect=self.db.__getitem__)
        with patch.object(embedding_routes, 'get_database', return_value=db):
            status, _ = asyncio.run(request('GET', '/api/embeddings/missing'))
        self.assertEqual(status, 404)
        db.client.close.assert_called_once()
        with patch.object(embedding_routes, 'get_database', side_effect=RuntimeError('secret-uri')):
            status, body = asyncio.run(request('GET', '/api/embeddings/testuser'))
        self.assertEqual(status, 503)
        self.assertNotIn('secret-uri', json.dumps(body))


if __name__ == '__main__':
    unittest.main()
