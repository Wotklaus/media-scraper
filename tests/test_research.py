"""Research lifecycle and HTTP integration without Atlas, TikTok or OpenAI."""
import asyncio
from copy import deepcopy
import json
import threading
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from backend import main, research_routes
from backend.research_models import StudyCreate, TERMINAL, StudyResponse
from backend.research_privacy import prepare_record
from backend.research_repository import ResearchRepository, ResearchConflict, LeaseLost
from backend.research_sources import SyntheticConnector, SourceFailure, validate_page
from backend.research_worker import ResearchWorker, run_worker
from research_fake import Clock, Database
from test_embeddings import request


def fixture(**kwargs):
    db, clock = Database(), Clock()
    repo = ResearchRepository(db, clock)
    study = repo.create(StudyCreate(**kwargs))
    return db, clock, repo, study['study_id']


def drain(repo, identity, clock, worker=None, ceiling=2000):
    worker = worker or ResearchWorker(repo)
    for _ in range(ceiling):
        if repo.detail(identity)['status'] in TERMINAL or repo.detail(identity)['status'] == 'paused':
            return repo.detail(identity)
        worker.tick()
        clock.advance(1)
    raise AssertionError('Worker did not settle')


class ContractsAndPrivacyTests(unittest.TestCase):
    def test_free_topics_targets_and_operational_bounds(self):
        for text in ('Tema nuevo Ω', '未知の話題', 'Cómo diseñar una ciudad', 'Texto libre sin catálogo'):
            self.assertEqual(StudyCreate(topic=text).topic, text)
        for target in (200, 400, 500, 1000, 731):
            self.assertEqual(StudyCreate(topic='x', target_records=target).target_records, target)
        for values in ({'topic': ' '}, {'topic': 'x', 'target_records': True},
                       {'topic': 'x', 'target_records': 0}, {'topic': 'x', 'target_records': 10001},
                       {'topic': 'x', 'source': 'unavailable-platform'}, {'topic': 'x', 'limits': {'batch_size': 101}},
                       {'topic': 'x', 'discipline': 'anything'}):
            with self.assertRaises(ValidationError):
                StudyCreate(**values)
        with patch.dict('os.environ', {'MEDIA_SCRAPER_RESEARCH_MAX_RECORDS': '15000'}):
            self.assertEqual(StudyCreate(topic='x', target_records=12000).target_records, 12000)

    def test_preparation_allowlist_redaction_and_study_scoped_keys(self):
        raw = {'record_id': 'comment-1', 'publication_id': 'publication-1',
            'text': 'Consulta a persona@example.com, @nombre, +593 99 123 4567 y https://example.com/perfil',
            'username': 'secret-user', 'name': 'Secret Name', 'avatar_url': 'private', 'extra': 'private'}
        result = prepare_record(raw, 'study', '01' * 32)
        self.assertEqual(set(result), {'record_key', 'publication_id', 'text', 'synthetic', 'privacy_version', 'redactions'})
        self.assertEqual(result['redactions'], 4)
        self.assertNotIn('persona@example.com', result['text'])
        self.assertNotIn('@nombre', result['text'])
        self.assertNotIn('123 4567', result['text'])
        self.assertNotIn('secret-user', str(result))
        self.assertEqual(result, prepare_record({**raw, 'username': 'different'}, 'study', '01' * 32))
        self.assertNotEqual(result['record_key'], prepare_record(raw, 'other-study', '01' * 32)['record_key'])
        for text in (None, '', ' ', 'x' * 4001, 'texto\x00', 'user@example.com', '123456789'):
            self.assertIsNone(prepare_record({**raw, 'text': text}, 'study', '01' * 32))

    def test_connector_pages_provenance_duplicates_and_memory_bound(self):
        connector = SyntheticConnector()
        config = StudyCreate(topic='arbitrary').source_config.model_dump()
        task = {'kind': 'acquire', 'publication_id': 'synthetic-video-00000', 'cursor': None}
        page = connector.read(topic='arbitrary', config=config, limit=20, attempt=1, **task)
        validate_page(page, task, 20)
        self.assertEqual(len(page.items), 20)
        self.assertEqual(page.next_cursor, '20')
        self.assertEqual(page.items[2]['record_id'], 'synthetic-comment-2')
        self.assertEqual(page.items[10]['record_id'], page.items[11]['record_id'])
        page.next_cursor = 'opaque-next-page'  # orchestration must not interpret provider cursors
        validate_page(page, task, 20)
        page.next_cursor = ''
        with self.assertRaises(SourceFailure):
            validate_page(page, task, 20)
        page.source = 'untrusted'
        with self.assertRaises(SourceFailure):
            validate_page(page, task, 20)


class LifecycleTests(unittest.TestCase):
    def test_creation_is_draft_read_only_queries_and_explicit_start(self):
        db, clock, repo, identity = fixture(topic='Cualquier tema')
        self.assertEqual(db.transaction_options['write_concern'].document, {'w': 'majority'})
        self.assertFalse(ResearchWorker(repo).tick())
        before = deepcopy({key: collection.rows for key, collection in db.collections.items()})
        self.assertEqual(repo.list()['total'], 1)
        self.assertEqual(repo.record_page(identity)['total'], 0)
        self.assertEqual(repo.task_page(identity)['total'], 1)
        self.assertEqual(before, {key: collection.rows for key, collection in db.collections.items()})
        self.assertNotIn('dedup_secret', str(repo.detail(identity)))
        self.assertEqual(repo.control(identity, 'start')['status'], 'queued')
        with self.assertRaises(ResearchConflict):
            repo.control(identity, 'start')

    def test_worker_entrypoint_once_and_storage_cleanup(self):
        db, clock, repo, identity = fixture(topic='x')
        repo.control(identity, 'start')
        with patch('backend.database.get_database', return_value=db):
            run_worker(once=True)
            self.assertEqual(db.closed, 1)
            self.assertEqual(repo.detail(identity)['counters']['publications_discovered'], 20)
            with patch.object(ResearchWorker, 'tick', side_effect=RuntimeError('synthetic storage failure')):
                with self.assertRaises(RuntimeError):
                    run_worker(once=True)
            self.assertEqual(db.closed, 2)

    def test_exact_target_deduplication_and_paginated_outputs(self):
        db, clock, repo, identity = fixture(topic='Tema sin categorías', target_records=73, limits={'batch_size': 7})
        repo.control(identity, 'start')
        with patch.object(main, 'scrape_profile', side_effect=AssertionError('Forbidden')), patch('backend.embeddings.OpenAI', side_effect=AssertionError('Forbidden')):
            result = drain(repo, identity, clock)
        self.assertEqual(result['status'], 'target_reached')
        self.assertEqual(result['counters']['prepared'], 73)
        self.assertGreater(result['counters']['duplicates'], 0)
        self.assertGreater(result['counters']['excluded'], 0)
        c = result['counters']
        self.assertEqual(c['received'], c['prepared'] + c['duplicates'] + c['excluded'])
        first = repo.record_page(identity, 0, 10)
        second = repo.record_page(identity, 10, 10)
        self.assertFalse({r['record_id'] for r in first['records']} & {r['record_id'] for r in second['records']})
        self.assertEqual(len(first['records']), 10)
        self.assertEqual(repo.record_page(identity, 100)['records'], [])
        self.assertEqual(repo.publication_page(identity, limit=3)['total'], 20)
        self.assertEqual(len(repo.publication_page(identity, limit=3)['publications']), 3)
        self.assertNotIn('synthetic_person', str(db['research_records'].rows))
        self.assertEqual(result['progress_percent'], 100)
        for action in ('resume', 'start', 'pause'):
            with self.assertRaises(ResearchConflict):
                repo.control(identity, action)

    def test_pause_resume_cancel_revoke_in_flight_writes(self):
        db, clock, repo, identity = fixture(topic='x', target_records=400)
        repo.control(identity, 'start')
        worker = ResearchWorker(repo)
        worker.tick()
        repo.control(identity, 'pause')
        self.assertFalse(worker.tick())
        self.assertEqual(repo.detail(identity)['status'], 'paused')
        repo.control(identity, 'resume')
        study = repo.claim_study()
        task = repo.claim_task(study)
        repo.control(identity, 'cancel')
        page = SyntheticConnector().read(topic='x', config=study['source_config'], kind=task['kind'],
            publication_id=task['publication_id'], cursor=task['cursor'], limit=50, attempt=task['attempts'])
        with self.assertRaises(LeaseLost):
            repo.stage_page(study, task, page)
        self.assertEqual(repo.detail(identity)['counters']['prepared'], 0)
        self.assertEqual(repo.detail(identity)['pending_tasks'], 0)

    def test_interruption_after_save_before_checkpoint_does_not_repeat_counts(self):
        class Crash(BaseException):
            pass
        db, clock, repo, identity = fixture(topic='x', target_records=100)
        repo.control(identity, 'start')
        ResearchWorker(repo).tick()  # discovery
        worker = ResearchWorker(repo, after_stage=lambda: (_ for _ in ()).throw(Crash()))
        with self.assertRaises(Crash):
            worker.tick()
        before = deepcopy(repo.detail(identity)['counters'])
        self.assertGreater(before['prepared'], 0)
        pending = next(row for row in db['research_tasks'].rows if row['pending'])
        self.assertIsNone(pending['last_checkpoint'])
        recovered = ResearchRepository(db, clock)  # new repository/worker, persisted state only
        class NoReads:
            def read(self, **kwargs):
                raise AssertionError('A pending page must not be fetched again')
        ResearchWorker(recovered, connector=NoReads()).tick()
        after = repo.detail(identity)['counters']
        for key in ('prepared', 'excluded', 'duplicates', 'batches'):
            self.assertEqual(before[key], after[key])
        result = drain(repo, identity, clock)
        self.assertEqual(result['counters']['prepared'], 100)
        self.assertEqual(repo.record_page(identity)['total'], 100)

    def test_transaction_rollback_and_expired_fencing(self):
        db, clock, repo, identity = fixture(topic='x')
        repo.control(identity, 'start')
        old = repo.claim_study()
        task = repo.claim_task(old)
        page = SyntheticConnector().read(topic='x', config=old['source_config'], kind='discover',
            publication_id=None, cursor=None, limit=50, attempt=1)
        db.fail_commit = True
        with self.assertRaises(RuntimeError):
            repo.stage_page(old, task, page)
        self.assertEqual(repo.detail(identity)['counters']['publications_discovered'], 0)
        self.assertEqual(repo.publication_page(identity)['total'], 0)
        clock.advance(61)
        new = repo.claim_study()
        self.assertNotEqual(old['lease_owner'], new['lease_owner'])
        with self.assertRaises(LeaseLost):
            repo.stage_page(old, task, page)
        self.assertEqual(repo.claim_task(new)['_id'], task['_id'])
        repo.release(new)

    def test_two_workers_only_one_reservation(self):
        db, clock, repo, identity = fixture(topic='x')
        repo.control(identity, 'start')
        barrier, results = threading.Barrier(2), []
        def claim():
            barrier.wait()
            results.append(repo.claim_study())
        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_duplicate_discovery_and_page_before_pause_are_recoverable(self):
        class RepeatedPublications(SyntheticConnector):
            def read(self, **kwargs):
                page = super().read(**kwargs)
                if kwargs['kind'] == 'discover':
                    for item in page.items:
                        number = int(item['publication_id'].split('-')[-1])
                        item['publication_id'] = f'synthetic-video-{number // 2:05d}'
                return page
        db, clock, repo, identity = fixture(topic='x', target_records=31)
        repo.control(identity, 'start')
        worker = ResearchWorker(repo, connector=RepeatedPublications())
        worker.tick()
        self.assertEqual(repo.detail(identity)['counters']['publications_discovered'], 10)
        self.assertEqual(repo.task_page(identity)['total'], 11)
        worker.after_stage = lambda: repo.control(identity, 'pause')
        worker.tick()
        paused = repo.detail(identity)
        self.assertEqual(paused['status'], 'paused')
        self.assertEqual(paused['counters']['prepared'], 31)
        repo.control(identity, 'resume')
        ResearchWorker(ResearchRepository(db, clock)).tick()
        self.assertEqual(repo.detail(identity)['status'], 'target_reached')
        self.assertEqual(repo.detail(identity)['counters']['prepared'], 31)

    def test_bad_provenance_and_unexpected_errors_never_expose_original_data(self):
        class BadSource(SyntheticConnector):
            def read(self, **kwargs):
                page = super().read(**kwargs)
                page.source = 'foreign'
                return page
        db, clock, repo, identity = fixture(topic='x')
        repo.control(identity, 'start')
        result = drain(repo, identity, clock, ResearchWorker(repo, connector=BadSource()))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['last_error'], 'invalid_provenance')
        self.assertEqual(repo.publication_page(identity)['total'], 0)
        class UnexpectedSource:
            def read(self, **kwargs):
                raise RuntimeError('private credential original payload')
        db, clock, repo, identity = fixture(topic='x')
        repo.control(identity, 'start')
        result = drain(repo, identity, clock, ResearchWorker(repo, connector=UnexpectedSource()))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['last_error'], 'processing_failed')
        self.assertNotIn('private', str(repo.task_page(identity)))
        self.assertEqual(repo.task_page(identity)['tasks'][0]['attempts'], 3)

    def test_exhaustion_partial_permanent_and_transient_failure(self):
        for failure, expected in (('none', 'exhausted'), ('permanent', 'partial'), ('transient', 'exhausted')):
            with self.subTest(failure=failure):
                db, clock, repo, identity = fixture(topic='x', target_records=400,
                    source_config={'publications': 2, 'comments_per_publication': 20, 'failure_mode': failure})
                repo.control(identity, 'start')
                result = drain(repo, identity, clock)
                self.assertEqual(result['status'], expected)
                self.assertLess(result['counters']['prepared'], 400)
                if failure == 'permanent':
                    self.assertEqual(result['failed_tasks'], 1)
        db, clock, repo, identity = fixture(topic='x', source_config={'failure_mode': 'permanent', 'failure_stage': 'discover'})
        repo.control(identity, 'start')
        self.assertEqual(drain(repo, identity, clock)['status'], 'failed')

    def test_time_budget_and_failure_messages_are_bounded(self):
        db, clock, repo, identity = fixture(topic='x', limits={'time_budget_seconds': 1})
        repo.control(identity, 'start')
        claimed = repo.claim_study()
        repo.release(claimed, 2.0)
        self.assertEqual(repo.detail(identity)['status'], 'paused')
        self.assertEqual(repo.detail(identity)['stop_reason'], 'time_budget_reached')
        repo.control(identity, 'resume')
        self.assertEqual(repo.raw_study(identity)['budget_used_seconds'], 0)


class EndpointTests(unittest.TestCase):
    def test_rest_lifecycle_validation_pagination_safe_errors_and_contracts(self):
        db = Database()
        with patch.object(research_routes, 'get_database', return_value=db):
            status, capabilities = asyncio.run(request('GET', '/api/research/sources'))
            self.assertEqual(status, 200)
            self.assertTrue(capabilities['synthetic'])
            for payload in ({'topic': ' '}, {'topic': 'x', 'target_records': 0}, {'topic': 'x', 'source': 'unavailable-platform'}):
                self.assertEqual(asyncio.run(request('POST', '/api/research/studies', body=json.dumps(payload).encode()))[0], 422)
            status, result = asyncio.run(request('POST', '/api/research/studies', body=json.dumps({'topic': '自由研究', 'target_records': 200}).encode()))
            self.assertEqual(status, 201)
            StudyResponse.model_validate(result)
            identity = result['study_id']
            self.assertNotIn('dedup_secret', str(result))
            for suffix in ('', '/progress', '/records', '/publications', '/tasks'):
                self.assertEqual(asyncio.run(request('GET', '/api/research/studies/' + identity + suffix))[0], 200)
            self.assertEqual(asyncio.run(request('GET', '/api/research/studies'))[1]['total'], 1)
            self.assertEqual(asyncio.run(request('GET', '/api/research/studies/' + identity + '/records', b'limit=101'))[0], 422)
            for action, expected in (('start', 202), ('start', 409), ('pause', 200), ('resume', 202), ('cancel', 200), ('resume', 409)):
                self.assertEqual(asyncio.run(request('POST', f'/api/research/studies/{identity}/{action}'))[0], expected)
            self.assertEqual(asyncio.run(request('GET', '/api/research/studies/00000000-0000-0000-0000-000000000000'))[0], 404)
            self.assertEqual(asyncio.run(request('GET', '/api/research/studies/invalid'))[0], 422)
        self.assertGreater(db.closed, 5)
        with patch.object(research_routes, 'get_database', side_effect=RuntimeError('secret mongodb uri')):
            status, body = asyncio.run(request('GET', '/api/research/studies'))
            self.assertEqual(status, 503)
            self.assertNotIn('secret', str(body))
        schema = main.app.openapi()
        self.assertIn('StudyResponse', schema['components']['schemas'])
