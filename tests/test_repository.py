"""Repository and API checks with an in-memory transaction fake, never Atlas."""
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timezone
import io
import unittest
from unittest.mock import Mock, patch

from pymongo.errors import AutoReconnect, OperationFailure

from backend import database, main, repository
from backend.normalizer import normalize_profile
from test_modes import request, sample_profile
from test_normalizer import fixture


class MemoryCollection:
    def __init__(self, database, name):
        self.database, self.name = database, name
        self.rows = []
        self.indexes = []

    def create_index(self, keys, **options):
        self.indexes.append((keys, options))

    def find_one(self, query, *, session):
        assert session is self.database.session
        return next((deepcopy(row) for row in self.rows if all(row.get(k) == v for k, v in query.items())), None)

    def update_one(self, query, update, *, upsert, session):
        assert upsert is True
        assert session is self.database.session
        if self.database.fail_collection == self.name:
            raise OperationFailure('synthetic driver message with private connection details')
        row = next((row for row in self.rows if all(row.get(k) == v for k, v in query.items())), None)
        if row is None:
            row = deepcopy(query)
            row.update(deepcopy(update.get('$setOnInsert', {})))
            self.rows.append(row)
        row.update(deepcopy(update.get('$set', {})))


class MemorySession:
    def __init__(self, database):
        self.database = database
        self.options = None
        self.closed = False
        self.retry_callback = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def with_transaction(self, callback, **options):
        self.options = options
        before = {name: deepcopy(collection.rows) for name, collection in self.database.collections.items()}
        def rollback():
            for name, rows in before.items():
                self.database[name].rows = deepcopy(rows)
        try:
            if self.retry_callback:
                callback(self)
                rollback()  # Simulate a transient abort before the driver retries.
            return callback(self)
        except Exception:
            rollback()
            raise


class MemoryDatabase:
    name = 'media_scraper'

    def __init__(self):
        self.collections = {}
        self.fail_collection = None
        self.session = MemorySession(self)
        self.client = Mock()
        self.client.start_session.return_value = self.session

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = MemoryCollection(self, name)
        return self.collections[name]


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.database = MemoryDatabase()
        self.repo = repository.ProfileRepository(self.database)

    def test_upserts_and_unique_indexes_with_string_ids_and_utc_dates(self):
        documents = normalize_profile(fixture())
        before = deepcopy(documents)
        self.repo.save(documents, run_id='run-1')
        self.repo.save(documents, run_id='run-2')
        self.assertEqual(documents, before)
        self.assertEqual(len(self.database['profiles'].rows), 1)
        self.assertEqual(len(self.database['publications'].rows), 2)
        self.assertEqual(len(self.database['comments'].rows), 2)
        self.assertEqual(len(self.database['extraction_runs'].rows), 2)
        for collection in ('profiles', 'publications', 'comments', 'extraction_runs'):
            self.assertTrue(any(options.get('unique') for _, options in self.database[collection].indexes))
        publication = self.database['publications'].rows[0]
        self.assertIsInstance(publication['publication_id'], str)
        self.assertEqual(publication['metrics']['comments_count'], 37)
        self.assertEqual(publication['retrieved_comments_count'], 2)
        self.assertEqual(self.database['comments'].rows[0]['comment_id'], '9876543210123456799')
        for run in self.database['extraction_runs'].rows:
            self.assertEqual(run['extracted_at'].tzinfo, timezone.utc)
            self.assertEqual(run['snapshot'], documents)
        self.assertTrue(self.database.session.closed)
        self.assertEqual(self.database.session.options['write_concern'].document, {'w': 'majority'})

    def test_same_run_retry_and_transaction_retry_are_idempotent(self):
        documents = normalize_profile(fixture())
        self.database.session.retry_callback = True
        self.repo.save(documents, run_id='run-1')
        self.database.session.retry_callback = False
        again = normalize_profile(fixture())  # normalized_at changes, not extraction contents.
        self.repo.save(again, run_id='run-1')
        self.assertEqual(len(self.database['extraction_runs'].rows), 1)
        self.assertEqual(len(self.database['comments'].rows), 2)
        self.assertEqual(self.database['profiles'].rows[0]['last_run_id'], 'run-1')
        again['profile']['nickname'] = 'Different query'
        with self.assertRaises(repository.PersistenceError):
            self.repo.save(again, run_id='run-1')
        self.assertEqual(self.database['extraction_runs'].rows[0]['snapshot'], documents)

    def test_empty_later_extraction_preserves_comments_and_previous_snapshot(self):
        first = normalize_profile(fixture())
        self.repo.save(first, run_id='first')
        second_profile = fixture()
        second_profile['videos'][0].update(comments='99', comments_list=[])
        second_profile['_meta']['warnings'] = ['Comments unavailable']
        second = normalize_profile(second_profile)
        self.repo.save(second, run_id='second')
        self.assertEqual(len(self.database['comments'].rows), 2)
        publication = self.database['publications'].rows[0]
        self.assertEqual(publication['metrics']['comments_count'], 99)
        self.assertEqual(publication['retrieved_comments_count'], 0)
        self.assertEqual(publication['comments_status'], 'not_recovered')
        self.assertIsNone(publication['comments_complete'])
        self.assertEqual(self.database['extraction_runs'].rows[0]['snapshot'], first)
        self.assertEqual(self.database['extraction_runs'].rows[1]['snapshot'], second)

    def test_comment_identity_is_scoped_to_publication_and_does_not_invent_cids(self):
        source = fixture()
        source['videos'][1]['comments_list'] = deepcopy(source['videos'][0]['comments_list'])
        self.repo.save(normalize_profile(source), run_id='first')
        self.repo.save(normalize_profile(source), run_id='second')
        rows = self.database['comments'].rows
        self.assertEqual(len(rows), 4)
        self.assertEqual(sum(row['comment_id'] is None for row in rows), 2)
        self.assertTrue(all(row['identity_key'].startswith(('cid:', 'dom:')) for row in rows))

    def test_failure_at_any_collection_rolls_back_every_write(self):
        self.repo.save(normalize_profile(fixture()), run_id='first')
        before = {name: deepcopy(collection.rows) for name, collection in self.database.collections.items()}
        for name in ('profiles', 'publications', 'comments', 'extraction_runs'):
            with self.subTest(collection=name):
                self.database.fail_collection = name
                with self.assertRaises(OperationFailure):
                    self.repo.save(normalize_profile(fixture()), run_id='failed')
                self.assertEqual({name: collection.rows for name, collection in self.database.collections.items()}, before)

    def test_demo_wrong_database_and_invalid_run_are_rejected(self):
        source = fixture()
        source['_meta']['mode'] = 'demo'
        with self.assertRaises(ValueError):
            self.repo.save(normalize_profile(source))
        self.assertEqual(self.database.collections, {})
        wrong = MemoryDatabase()
        wrong.name = 'another_database'
        with self.assertRaises(repository.PersistenceError):
            repository.ProfileRepository(wrong)
        with self.assertRaises(ValueError):
            self.repo.save(normalize_profile(fixture()), run_id='')

    @patch.object(repository, 'get_database')
    def test_wrapper_normalizes_saves_and_closes_client(self, connect):
        connect.return_value = self.database
        result = repository.save_profile(fixture())
        self.assertEqual(self.database['extraction_runs'].rows[0]['run_id'], result)
        self.database.client.close.assert_called_once()

    @patch.object(repository, 'get_database')
    def test_wrapper_errors_are_redacted_and_close_client(self, connect):
        for phase in ('connect', 'index', 'write'):
            with self.subTest(phase=phase):
                db = MemoryDatabase()
                connect.side_effect = None
                connect.return_value = db
                if phase == 'connect':
                    connect.side_effect = AutoReconnect('mongodb://private-credentials')
                elif phase == 'index':
                    db['profiles'].create_index = Mock(side_effect=OperationFailure('private-credentials'))
                else:
                    db.fail_collection = 'comments'
                with self.assertRaises(repository.PersistenceError) as error:
                    repository.save_profile(fixture())
                self.assertEqual(str(error.exception), repository.PERSISTENCE_FAILURE)
                if phase != 'connect':
                    db.client.close.assert_called_once()

    @patch.object(repository, 'get_database')
    def test_demo_never_connects(self, connect):
        source = fixture()
        source['_meta']['mode'] = 'demo'
        with self.assertRaises(repository.PersistenceError):
            repository.save_profile(source)
        connect.assert_not_called()


class DatabaseTests(unittest.TestCase):
    @patch.object(database, 'load_mongodb_config', return_value=('mongodb://synthetic.invalid', 'media_scraper'))
    @patch.object(database, 'MongoClient')
    def test_ping_failure_closes_client(self, client, config):
        client.return_value.admin.command.side_effect = AutoReconnect('synthetic failure')
        with self.assertRaises(AutoReconnect):
            database.get_database()
        client.return_value.close.assert_called_once()


class PersistenceAPITests(unittest.TestCase):
    def test_real_endpoint_persists_normalized_data_and_returns_original_json(self):
        db = MemoryDatabase()
        source = sample_profile()
        before = deepcopy(source)
        with patch.object(main, 'scrape_profile', return_value=source), patch.object(repository, 'get_database', return_value=db), patch.object(main, 'print_profile'):
            status, data = asyncio.run(request('/api/profile/test_only'))
        self.assertEqual(status, 200)
        self.assertEqual(data, before)
        self.assertEqual(source, before)
        self.assertEqual(len(db['publications'].rows), 10)
        self.assertEqual(len(db['extraction_runs'].rows), 1)
        db.client.close.assert_called_once()

    def test_explicit_real_also_saves_and_demo_never_saves(self):
        with patch.object(main, 'scrape_profile', return_value=sample_profile()), patch.object(main, 'load_capture', return_value=sample_profile()), patch.object(main, 'save_profile') as save, patch.object(main, 'print_profile'):
            status, _ = asyncio.run(request('/api/profile/test_only', b'mode=real'))
            self.assertEqual(status, 200)
            save.assert_called_once()
            save.reset_mock()
            status, _ = asyncio.run(request('/api/profile/test_only', b'mode=demo'))
            self.assertEqual(status, 200)
            save.assert_not_called()

    def test_atlas_failure_is_503_with_safe_detail_and_no_success_output(self):
        output = io.StringIO()
        with patch.object(main, 'scrape_profile', return_value=sample_profile()), patch.object(repository, 'get_database', side_effect=AutoReconnect('mongodb://private-credentials')), redirect_stdout(output):
            status, data = asyncio.run(request('/api/profile/test_only'))
        self.assertEqual(status, 503)
        self.assertEqual(data['detail'], repository.PERSISTENCE_FAILURE)
        self.assertNotIn('private-credentials', str(data))
        self.assertEqual(output.getvalue(), '')
