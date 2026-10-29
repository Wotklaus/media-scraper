"""Opt-in real MongoDB tests. Refuses pre-existing DBs and non-local test servers.

Not auto-discovered by unittest. Never loads backend/.env or drops databases.
Only for a disposable replica set started with enableTestCommands=1.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import threading
import time
import tracemalloc
import unittest
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient, monitoring
from pymongo.errors import DuplicateKeyError

from backend.research_models import StudyCreate, TERMINAL
from backend.research_repository import ResearchRepository, LeaseLost
from backend.research_sources import Page, SyntheticConnector, validate_page
from backend.research_worker import ResearchWorker


class CommandCounts(monitoring.CommandListener):
    """Keep counts only, never command/reply bodies or error messages."""
    def __init__(self):
        self.commands = Counter()
        self.failures = Counter()
        self.lock = threading.Lock()

    def started(self, event):
        with self.lock:
            self.commands[event.command_name] += 1

    def succeeded(self, event):
        pass

    def failed(self, event):
        with self.lock:
            self.failures[event.command_name] += 1

    def failure_count(self):
        with self.lock:
            return sum(self.failures.values())


class Clock:
    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def __call__(self):
        return self.now


class Context:
    def __init__(self, uri, database, replica_set):
        parsed = urlsplit(uri)
        query = parse_qs(parsed.query)
        if (parsed.scheme != 'mongodb' or parsed.hostname not in ('127.0.0.1', 'localhost')
                or parsed.username is not None or parsed.password is not None
                or parsed.port in (None, 27017) or parsed.path not in ('', '/')
                or query.get('directConnection') != ['true']
                or query.get('replicaSet') != [replica_set]
                or replica_set != 'msIntegration'
                or not database.startswith('media_scraper_integration_')
                or len(database) > 63 or not database.replace('_', '').isalnum()):
            raise RuntimeError('Refused: use a separate local test port, msIntegration and a new integration database.')
        self.uri, self.name = uri, database
        self.monitor = CommandCounts()
        self.client = self.new_client(self.monitor)
        hello = self.client.admin.command('hello')
        if hello.get('setName') != replica_set or not hello.get('isWritablePrimary'):
            self.client.close()
            raise RuntimeError('Refused: the isolated replica set is not writable primary.')
        if database in self.client.list_database_names():
            self.client.close()
            raise RuntimeError('Refused: database already exists. No writes or cleanup performed.')
        self.db = self.client[database]
        self.db['_integration_manifest'].insert_one({
            '_id': 'isolation', 'purpose': 'disposable-synthetic-integration',
            'created_at': datetime.now(timezone.utc), 'synthetic': True})
        self.reports = []
        self.environment = {'mongo_version': self.client.admin.command('buildInfo')['version'],
            'replica_set': replica_set, 'database': database, 'host': parsed.hostname,
            'port': parsed.port, 'python': sys.version.split()[0], 'synthetic': True,
            'preexisting_database': False, 'real_mongodb': True, 'replica_members': len(hello.get('hosts', []))}

    def new_client(self, listener=None):
        return MongoClient(self.uri, appname='media-scraper-isolated-integration',
            serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, socketTimeoutMS=15000,
            event_listeners=[listener] if listener else [])

    def failpoint(self, data=None):
        command = {'configureFailPoint': 'failCommand', 'mode': {'times': 1} if data else 'off'}
        if data:
            command['data'] = data
        self.client.admin.command(command)


CHILD = '''
import os,sys
from pymongo import MongoClient
from backend.research_repository import ResearchRepository
from backend.research_worker import ResearchWorker
client=MongoClient(sys.argv[1],serverSelectionTimeoutMS=5000)
repo=ResearchRepository(client[sys.argv[2]])
if sys.argv[3]=='before':
    study=repo.claim_study()
    if study is None or repo.claim_task(study) is None: os._exit(72)
    os._exit(71)
ResearchWorker(repo,after_stage=lambda:os._exit(71)).tick()
os._exit(72)
'''


class MongoResearchIntegration(unittest.TestCase):
    context = None

    def setUp(self):
        self.repo = ResearchRepository(self.context.db)
        self.identity = None

    def tearDown(self):
        self.context.failpoint()  # only this explicitly disposable test server
        if self.identity and self.repo.raw_study(self.identity)['status'] not in TERMINAL:
            self.repo.control(self.identity, 'cancel')

    def create(self, target=73, **kwargs):
        values = {'topic': 'Contenido sintético de integración', 'target_records': target,
                  'limits': {'lease_seconds': 10, 'time_budget_seconds': 3600}, **kwargs}
        result = self.repo.create(StudyCreate(**values))
        self.identity = result['study_id']
        self.repo.control(self.identity, 'start')
        return self.identity

    def page(self, study, task):
        page = SyntheticConnector().read(topic=study['topic'], config=study['source_config'],
            kind=task['kind'], publication_id=task['publication_id'], cursor=task['cursor'],
            limit=study['limits']['batch_size'], attempt=task['attempts'])
        validate_page(page, task, study['limits']['batch_size'], study['source'])
        return page

    def drain(self, worker=None):
        worker = worker or ResearchWorker(self.repo)
        for _ in range(2000):
            if self.repo.raw_study(self.identity)['status'] in TERMINAL:
                return self.audit()
            worker.tick()
        self.fail('Research did not terminate within its controlled batch limit')

    def audit(self):
        study = self.repo.raw_study(self.identity)
        counters = study['counters']
        query = {'study_id': self.identity}
        self.assertEqual(counters['prepared'], self.repo.records.count_documents(query))
        self.assertEqual(counters['received'], counters['prepared'] + counters['duplicates'] + counters['excluded'])
        self.assertLessEqual(counters['prepared'], study['target_records'])
        self.assertEqual(counters['publications_discovered'], self.repo.publications.count_documents(query))
        self.assertEqual(counters['publications_processed'], self.repo.publications.count_documents({**query, 'processed': True}))
        self.assertEqual(self.repo.tasks.count_documents({**query, 'kind': 'acquire'}), counters['publications_discovered'])
        if study['status'] == 'target_reached':
            self.assertEqual(counters['prepared'], study['target_records'])
            self.assertEqual(self.repo.tasks.count_documents({**query, 'status': {'$in': ['queued', 'processing', 'retry_wait']}}), 0)
            self.assertEqual(self.repo.tasks.count_documents({**query, 'pending': {'$ne': None}}), 0)
        return study

    def record_digest(self):
        rows = self.repo.records.find({'study_id': self.identity}, {'record_key': 1, 'text': 1}).sort('_id', 1)
        return hashlib.sha256(json.dumps(list(rows), sort_keys=True, default=str).encode()).hexdigest()

    def test_01_persistence_indexes_rollback_and_pagination(self):
        self.create(73)
        worker = ResearchWorker(self.repo)
        worker.tick()
        self.assertEqual(self.repo.detail(self.identity)['counters']['prepared'], 0)
        worker.tick()
        self.assertGreater(self.repo.detail(self.identity)['counters']['prepared'], 0)
        self.drain()
        first = self.repo.record_page(self.identity, 0, 11)
        second = self.repo.record_page(self.identity, 11, 11)
        self.assertEqual(first['total'], 73)
        self.assertEqual(len(first['records']), 11)
        self.assertFalse({r['record_id'] for r in first['records']} & {r['record_id'] for r in second['records']})
        for collection, fields in ((self.repo.records, [('study_id', 1), ('record_key', 1)]),
                (self.repo.tasks, [('study_id', 1), ('kind', 1), ('publication_id', 1)]),
                (self.repo.publications, [('study_id', 1), ('source', 1), ('publication_id', 1)])):
            self.assertTrue(any(info.get('unique') and info['key'] == fields for info in collection.index_information().values()))
            original = collection.find_one({'study_id': self.identity})
            duplicate = {key: value for key, value in original.items() if key != '_id'}
            before = collection.count_documents({'study_id': self.identity})
            with self.assertRaises(DuplicateKeyError):
                collection.insert_one(duplicate)
            self.assertEqual(collection.count_documents({'study_id': self.identity}), before)
        marker = str(uuid4())
        def abort(session):
            self.repo.records.insert_one({'_id': marker, 'study_id': self.identity,
                'record_key': marker, 'text': 'Synthetic rollback marker'}, session=session)
            raise RuntimeError('intentional transaction abort')
        with self.assertRaises(RuntimeError):
            self.repo.transaction(abort)
        self.assertIsNone(self.repo.records.find_one({'_id': marker}))
        self.audit()

    def crash_and_recover(self, location):
        self.create(73)
        ResearchWorker(self.repo).tick()  # discovery confirmed, acquisition still pending
        before = deepcopy(self.repo.raw_study(self.identity)['counters'])
        process = subprocess.run([sys.executable, '-B', '-c', CHILD,
            self.context.uri, self.context.name, location], cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 71, 'Child must terminate via os._exit at the requested boundary')
        recovery_started = time.perf_counter()
        study = self.repo.raw_study(self.identity)
        self.assertIsNotNone(study['lease_owner'])
        staged = deepcopy(study['counters'])
        if location == 'before':
            self.assertEqual(before['prepared'], staged['prepared'])
            self.assertEqual(before['batches'], staged['batches'])
        else:
            self.assertGreater(staged['prepared'], before['prepared'])
            self.assertIsNotNone(self.repo.tasks.find_one({'study_id': self.identity, 'pending': {'$ne': None}}))
        digest = self.record_digest()
        self.assertIsNone(self.repo.claim_study())  # real, unexpired reservation blocks another worker
        lease_until = study['lease_until'].replace(tzinfo=timezone.utc)
        deadline = time.monotonic() + 15
        while datetime.now(timezone.utc) <= lease_until:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        execution_started = time.perf_counter()
        restarted_client = self.context.new_client()
        try:
            restarted = ResearchRepository(restarted_client[self.context.name])
            ResearchWorker(restarted).tick()
        finally:
            restarted_client.close()
        if location == 'after':
            confirmed = self.repo.raw_study(self.identity)['counters']
            for key in ('prepared', 'excluded', 'duplicates', 'received', 'batches'):
                self.assertEqual(staged[key], confirmed[key])
            self.assertEqual(digest, self.record_digest())
        execution_seconds = time.perf_counter() - execution_started
        total_seconds = time.perf_counter() - recovery_started
        self.drain()
        self.context.reports.append({'scenario': f'process_exit_{location}_save',
            'recovery_seconds_including_lease': round(total_seconds, 4),
            'recovery_execution_seconds': round(execution_seconds, 4), 'prepared_final': 73})

    def test_02_process_exit_before_save(self):
        self.crash_and_recover('before')

    def test_03_process_exit_after_save_before_checkpoint(self):
        self.crash_and_recover('after')

    def test_04_expired_and_replaced_token_cannot_confirm(self):
        clock = Clock()
        self.repo = ResearchRepository(self.context.db, clock)
        self.create(73)
        ResearchWorker(self.repo).tick()
        old = self.repo.claim_study()
        task = self.repo.claim_task(old)
        self.repo.stage_page(old, task, self.page(old, task))
        clock.now += timedelta(seconds=11)
        new = self.repo.claim_study()
        self.assertIsNotNone(new)
        self.assertNotEqual(old['lease_owner'], new['lease_owner'])
        new_task = self.repo.claim_task(new)
        before = self.record_digest()
        with self.assertRaises(LeaseLost):
            self.repo.confirm_page(old, task)
        self.repo.confirm_page(new, new_task)
        self.assertEqual(before, self.record_digest())
        self.repo.release(new)
        self.drain()

    def test_05_atomic_reservation_and_concurrent_confirmation(self):
        self.create(73)
        ResearchWorker(self.repo).tick()
        barrier = threading.Barrier(2)
        def reserve():
            client = self.context.new_client()
            try:
                barrier.wait(timeout=10)
                return ResearchRepository(client[self.context.name]).claim_study()
            finally:
                client.close()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reserve) for _ in range(2)]
            claims = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        study = next(claim for claim in claims if claim)
        task = self.repo.claim_task(study)
        self.repo.stage_page(study, task, self.page(study, task))
        before = deepcopy(self.repo.raw_study(self.identity)['counters'])
        barrier = threading.Barrier(2)
        def confirm():
            client = self.context.new_client()
            try:
                barrier.wait(timeout=10)
                try:
                    ResearchRepository(client[self.context.name]).confirm_page(study, task)
                    return 'confirmed'
                except LeaseLost:
                    return 'rejected'
            finally:
                client.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(confirm) for _ in range(2)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(outcomes, ['confirmed', 'rejected'])
        after = self.repo.raw_study(self.identity)['counters']
        self.assertEqual(before['prepared'], after['prepared'])
        self.assertEqual(before['batches'], after['batches'])
        self.repo.release(study)
        self.drain()

    def test_06_real_connection_close_and_commit_retry(self):
        self.create(73)
        ResearchWorker(self.repo).tick()
        study = self.repo.claim_study()
        task = self.repo.claim_task(study)
        page = self.page(study, task)
        before = self.context.monitor.failure_count()
        started = time.perf_counter()
        self.context.failpoint({'failCommands': ['update'], 'closeConnection': True})
        try:
            self.repo.stage_page(study, task, page)
        finally:
            self.context.failpoint()
        network_seconds = time.perf_counter() - started
        self.assertGreater(self.context.monitor.failure_count(), before)
        staged = deepcopy(self.repo.raw_study(self.identity)['counters'])
        before_commit = self.context.monitor.failure_count()
        self.context.failpoint({'failCommands': ['commitTransaction'], 'errorCode': 91,
                               'errorLabels': ['UnknownTransactionCommitResult']})
        try:
            self.repo.confirm_page(study, task)
        finally:
            self.context.failpoint()
        self.assertGreater(self.context.monitor.failure_count(), before_commit)
        self.assertEqual(staged['prepared'], self.repo.raw_study(self.identity)['counters']['prepared'])
        self.repo.release(study)
        self.drain()
        self.context.reports.append({'scenario': 'real_connection_close_and_commit_retry',
            'failed_wire_commands': self.context.monitor.failure_count() - before,
            'network_recovery_seconds': round(network_seconds, 4), 'prepared_final': 73})

    def test_07_repeated_page_unique_records_and_exact_counters(self):
        self.create(1000)
        ResearchWorker(self.repo).tick()
        study = self.repo.claim_study()
        task = self.repo.claim_task(study)
        page = self.page(study, task)
        self.repo.stage_page(study, task, page)
        self.repo.confirm_page(study, task)
        self.repo.release(study)
        first = deepcopy(self.repo.raw_study(self.identity)['counters'])
        digest = self.record_digest()
        study = self.repo.claim_study()
        task = self.repo.claim_task(study)
        actual = self.page(study, task)
        repeated = Page(actual.source, actual.kind, actual.publication_id, actual.cursor,
                        actual.next_cursor, page.items[:len(actual.items)])
        validate_page(repeated, task, study['limits']['batch_size'])
        self.repo.stage_page(study, task, repeated)
        self.repo.confirm_page(study, task)
        self.repo.release(study)
        after = self.audit()['counters']
        self.assertEqual(first['prepared'], after['prepared'])
        self.assertGreater(after['duplicates'], first['duplicates'])
        self.assertEqual(digest, self.record_digest())

    def test_08_pause_resume_cancel_pending_batch(self):
        self.create(73)
        ResearchWorker(self.repo).tick()
        study = self.repo.claim_study()
        task = self.repo.claim_task(study)
        self.repo.stage_page(study, task, self.page(study, task))
        prepared = self.repo.detail(self.identity)['counters']['prepared']
        self.repo.control(self.identity, 'pause')
        self.assertFalse(ResearchWorker(self.repo).tick())
        with self.assertRaises(LeaseLost):
            self.repo.confirm_page(study, task)
        self.repo.control(self.identity, 'resume')
        ResearchWorker(self.repo).tick()
        self.assertEqual(prepared, self.repo.detail(self.identity)['counters']['prepared'])
        self.repo.control(self.identity, 'cancel')
        self.assertFalse(ResearchWorker(self.repo).tick())
        self.assertEqual(prepared, self.audit()['counters']['prepared'])

    def test_09_real_load_400_and_1000(self):
        for target in (400, 1000):
            with self.subTest(target=target):
                failures_before = self.context.monitor.failure_count()
                tracemalloc.start()
                started = time.perf_counter()
                self.create(target, limits={'lease_seconds': 60, 'time_budget_seconds': 3600})
                result = self.drain()
                elapsed = time.perf_counter() - started
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                report = {'scenario': 'real_mongodb_load', 'target': target,
                    'state': result['status'], **result['counters'], 'total_seconds': round(elapsed, 4),
                    'python_peak_mib': round(peak / 1024**2, 3),
                    'client_process_peak_rss_mib_linux': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 3),
                    'failed_wire_commands': self.context.monitor.failure_count() - failures_before}
                self.context.reports.append(report)
                self.assertEqual(result['status'], 'target_reached')
                self.assertEqual(report['failed_wire_commands'], 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uri', required=True, help='Explicit local disposable replica-set URI; never backend/.env')
    parser.add_argument('--database', default='media_scraper_integration_' + uuid4().hex[:16])
    parser.add_argument('--confirm-isolated', action='store_true', required=True)
    args = parser.parse_args()
    context = Context(args.uri, args.database, 'msIntegration')
    MongoResearchIntegration.context = context
    try:
        print(json.dumps({'environment': context.environment}), flush=True)
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MongoResearchIntegration))
        print(json.dumps({'reports': context.reports, 'tests_run': result.testsRun,
                         'failures': len(result.failures), 'errors': len(result.errors)}, ensure_ascii=False), flush=True)
        return 0 if result.wasSuccessful() else 1
    finally:
        context.failpoint()
        context.client.close()


if __name__ == '__main__':
    raise SystemExit(main())
