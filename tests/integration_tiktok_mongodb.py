"""Opt-in full TikTok flow: real Chromium/V1/MongoDB, controlled source content.

Never uses backend/.env, the operator's browser profile or TikTok's network.
Requires a NEW isolated DB and the disposable msIntegration replica set.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from playwright.async_api import async_playwright
from pymongo import MongoClient

from integration_research_mongodb import Context, Clock
from backend import research_routes
from backend.reference_runtime import SharedBrowser
from backend.research_models import TERMINAL
from backend.research_repository import ResearchRepository
from backend.research_tiktok import TikTokConnector
from backend.research_worker import ResearchWorker
from backend.vendor.scrapingtiktok import tiktok_scraper as original

VIDEOS = [f'https://www.tiktok.com/@fixture/video/{i}' for i in (333, 444, 555)]


class BrowserSource:
    def __init__(self, deny=None):
        self.deny = deny or {}
        self.searches, self.extractions, self.requests = 0, [], []

    @contextmanager
    def installed(self):
        handles = []
        source = self
        extract = original.TikTokScraper._extract_single_video_details

        async def tracked(engine, context, video_url, max_comments=20):
            source.extractions.append({'video': video_url, 'requested': max_comments})
            return await extract(engine, context, video_url, max_comments=max_comments)

        async def setup(engine, playwright):
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(service_workers='block')
            handles.append((context, browser))
            engine._shared_context = context

            async def route_request(route):
                parsed = urlsplit(route.request.url)
                if parsed.hostname != 'www.tiktok.com':
                    await route.abort()
                    return
                if parsed.path == '/search':
                    source.searches += 1
                    links = ''.join(f'<a href="{url}">Fixture bitcoin</a>' for url in VIDEOS)
                    links += f'<a href="{VIDEOS[0]}?tracking=1">Duplicate</a><a href="https://other.invalid/@x/video/1">Foreign</a>'
                    body = '<main></main><script>setTimeout(()=>document.querySelector("main").innerHTML='+json.dumps(links)+', 300)</script>'
                    await route.fulfill(content_type='text/html', body=body)
                elif parsed.path == '/api/comment/list/':
                    video = parse_qs(parsed.query)['aweme_id'][0]
                    source.requests.append(video)
                    if video in source.deny:
                        await route.fulfill(status=source.deny[video], body='Controlled denial')
                        return
                    comments = [{'cid': str(i), 'aweme_id': video, 'user': {'unique_id': 'reader'},
                        'text': f'Bitcoin educativo {i} persona@example.invalid @lector'} for i in range(1, 4)]
                    comments += [comments[0], {**comments[0], 'cid': '999', 'aweme_id': 'foreign'}]
                    await route.fulfill(json={'status_code': 0, 'aweme_id': video, 'comments': comments})
                elif parsed.path.startswith('/@fixture/video/'):
                    video = parsed.path.split('/')[-1]
                    item = {'id': video, 'author': {'uniqueId': 'fixture'}, 'desc': 'Bitcoin educativo',
                            'stats': {'playCount': 20, 'commentCount': 3}}
                    body = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'+json.dumps({'__DEFAULT_SCOPE__': {'webapp.video-detail': {'itemInfo': {'itemStruct': item}}}})+'</script>'
                    body += '<button data-e2e="comment-icon" onclick="fetch(\'/api/comment/list/?aweme_id='+video+'\')">Comments</button>'
                    await route.fulfill(content_type='text/html', body=body)
                else:
                    await route.fulfill(status=404, body='Controlled unused route')

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
             patch.object(original.TikTokScraper, '_extract_single_video_details', tracked), \
             patch.object(original, 'asyncio', SimpleNamespace(sleep=brief_sleep)):
            yield self


class TikTokMongoFlow(unittest.TestCase):
    context = None

    def setUp(self):
        self.clock = Clock()
        self.repo = ResearchRepository(self.context.db, self.clock)
        self.identity = None
        self.app = FastAPI()
        self.app.include_router(research_routes.router)
        self.app.dependency_overrides[research_routes.research_repository] = lambda: self.repo

    def tearDown(self):
        if self.identity and self.repo.detail(self.identity)['status'] not in TERMINAL:
            self.repo.control(self.identity, 'cancel')

    def api(self, method, suffix, payload=None):
        async def invoke():
            path = '/api/research' + suffix
            body = json.dumps(payload).encode() if payload is not None else b''
            messages = []
            async def receive():
                return {'type': 'http.request', 'body': body, 'more_body': False}
            async def send(message):
                messages.append(message)
            await self.app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
                'query_string': b'', 'headers': [(b'content-type', b'application/json')],
                'client': ('127.0.0.1', 1), 'server': ('127.0.0.1', 80), 'root_path': ''}, receive, send)
            status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
            self.assertLess(status, 300)
            return json.loads(b''.join(m.get('body', b'') for m in messages))
        return asyncio.run(invoke())

    def create(self, target=4, max_publications=3):
        study = self.api('POST', '/studies', {'topic': 'bitcoin fixture — NOT REAL', 'source': 'tiktok',
            'target_records': target, 'limits': {'batch_size': 2},
            'source_config': {'max_publications': max_publications, 'max_comments_per_publication': 2, 'max_scrolls': 1}})
        self.identity = study['study_id']
        self.api('POST', f'/studies/{self.identity}/start')

    def audit(self):
        study = self.api('GET', f'/studies/{self.identity}/progress')
        # Read with another MongoClient: memory in the worker is not persistence evidence.
        with self.context.new_client() as client:
            db = client[self.context.name]
            records = list(db.research_records.find({'study_id': self.identity}))
            self.assertEqual(study['counters']['prepared'], len(records))
            self.assertLessEqual(len(records), study['target_records'])
            self.assertEqual(len({r['record_key'] for r in records}), len(records))
            self.assertEqual(study['counters']['received'], study['counters']['prepared'] + study['counters']['duplicates'] + study['counters']['excluded'])
            self.assertEqual(study['counters']['publications_processed'], db.research_publications.count_documents({'study_id': self.identity, 'processed': True}))
            for record in records:
                self.assertNotIn('persona@example.invalid', record['text'])
                self.assertNotIn('@lector', record['text'])
                self.assertNotIn('username', record)
        return study

    def tick(self):
        self.assertTrue(ResearchWorker(self.repo, TikTokConnector()).tick())
        return self.audit()

    def test_01_search_v1_prepare_commit_next_video_target(self):
        self.create()
        with BrowserSource().installed() as source:
            self.assertEqual(self.tick()['counters']['publications_discovered'], 2)
            self.assertEqual(self.tick()['counters']['prepared'], 2)
            result = self.tick()
        self.assertEqual(result['status'], 'target_reached')
        self.assertEqual(result['counters']['prepared'], 4)
        self.assertEqual(source.searches, 1)
        self.assertEqual([e['video'] for e in source.extractions], VIDEOS[:2])
        self.assertEqual(result['pending_tasks'], 0)
        self.assertEqual(self.api('GET', f'/studies/{self.identity}/records')['total'], 4)
        self.context.reports.append({'scenario': 'two_consecutive_videos', 'searches': source.searches,
            'v1_calls': len(source.extractions), 'committed': 4, 'target_reached': True})

    def test_02_death_after_commit_recovers_without_reextracting(self):
        self.create()
        with BrowserSource().installed():
            self.tick()
        child = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--uri', self.context.uri,
            '--database', self.context.name, '--confirm-isolated', '--child-study', self.identity],
            capture_output=True, text=True, timeout=40)
        self.assertEqual(child.returncode, 71, child.stderr)
        self.assertEqual(self.audit()['counters']['prepared'], 2)
        task = self.repo.tasks.find_one({'study_id': self.identity, 'publication_id': VIDEOS[0]})
        self.assertIsNotNone(task['pending'])
        self.clock.now = datetime.now(timezone.utc) + timedelta(seconds=61)
        # A fresh repository/client and worker must confirm pending data without source I/O.
        with self.context.new_client() as client:
            fresh = ResearchRepository(client[self.context.name], self.clock)
            with patch.object(TikTokConnector, 'read', side_effect=AssertionError('Must not reextract')):
                self.assertTrue(ResearchWorker(fresh, TikTokConnector()).tick())
        self.assertEqual(self.audit()['counters']['prepared'], 2)
        with BrowserSource().installed() as source:
            result = self.tick()
        self.assertEqual(result['counters']['prepared'], 4)
        self.assertEqual([e['video'] for e in source.extractions], [VIDEOS[1]])
        self.assertEqual(source.searches, 0)
        self.context.reports.append({'scenario': 'process_death_after_commit', 'exit_code': 71,
            'retained': 2, 'reextracted_pending_video': False, 'final_committed': 4,
            'lease_expiry': 'controlled application clock +61s'})

    def test_03_confirmed_restriction_pause_resume_preserves_progress(self):
        self.create()
        with BrowserSource({'444': 403}).installed() as source:
            self.tick()
            self.tick()
            paused = self.tick()
            self.assertEqual(paused['status'], 'paused')
            self.assertEqual(paused['last_error'], 'access_restricted')
            self.assertEqual(paused['counters']['prepared'], 2)
            self.assertFalse(ResearchWorker(self.repo, TikTokConnector()).tick())
            task = self.repo.tasks.find_one({'study_id': self.identity, 'publication_id': VIDEOS[1]})
            self.assertIsNone(task['pending'])
            self.assertIsNone(task['cursor'])
            self.api('POST', f'/studies/{self.identity}/resume')
            self.clock.now += timedelta(seconds=4)
            source.deny.clear()
            result = self.tick()
        self.assertEqual(result['status'], 'target_reached')
        self.assertIsNone(result['last_error'])
        self.assertEqual(result['counters']['prepared'], 4)
        self.assertEqual(source.searches, 1)
        self.context.reports.append({'scenario': 'confirmed_403_pause_resume', 'retained': 2,
                                     'final_committed': 4, 'stale_error_cleared': True})

    def test_04_transient_comment_load_error_retries_same_video(self):
        self.create()
        with BrowserSource({'444': 503}).installed() as source:
            self.tick()
            self.tick()
            result = self.tick()
            self.assertEqual(result['counters']['prepared'], 2)
            self.assertEqual(result['counters']['publications_processed'], 1)
            self.assertEqual(result['last_error'], 'source_load_timeout')
            self.assertNotEqual(result['status'], 'paused')
            self.assertFalse(ResearchWorker(self.repo, TikTokConnector()).tick())
            self.assertEqual(source.searches, 1)
            source.deny.clear()
            self.clock.now += timedelta(seconds=4)
            result = self.tick()
        self.assertEqual(result['counters']['prepared'], 4)
        self.assertEqual(result['status'], 'target_reached')
        self.assertEqual([e['video'] for e in source.extractions], [VIDEOS[0], VIDEOS[1], VIDEOS[1]])
        self.context.reports.append({'scenario': '503_retry', 'retained': 2, 'final_committed': 4,
                                     'unnecessary_rediscovery': False})

    def test_05_limits_do_not_claim_target(self):
        self.create(target=5, max_publications=2)
        with BrowserSource().installed() as source:
            self.tick()
            self.tick()
            result = self.tick()
        self.assertEqual(result['status'], 'exhausted')
        self.assertEqual(result['counters']['prepared'], 4)
        self.assertEqual(result['progress_percent'], 80)
        self.assertEqual(source.searches, 1)
        self.context.reports.append({'scenario': 'configured_limits', 'committed': 4,
                                     'target': 5, 'state': 'exhausted'})

    def test_06_remaining_target_limits_engine_request(self):
        self.create(target=3)
        with BrowserSource().installed() as source:
            self.tick()
            self.tick()
            result = self.tick()
        self.assertEqual(result['status'], 'target_reached')
        self.assertEqual(result['counters']['prepared'], 3)
        # The lookahead can ask one additional comment, but never a whole default batch.
        self.assertLessEqual(source.extractions[-1]['requested'], 2)
        self.context.reports.append({'scenario': 'remaining_target', 'committed': 3,
                                     'last_engine_request': source.extractions[-1]['requested']})


def child_stage(uri, database, study_id):
    parsed = urlsplit(uri)
    query = parse_qs(parsed.query)
    if (parsed.scheme != 'mongodb' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or parsed.username is not None or parsed.password is not None or parsed.port in (None, 27017)
            or query.get('replicaSet') != ['msIntegration'] or query.get('directConnection') != ['true']
            or not database.startswith('media_scraper_integration_') or len(database) > 63
            or not database.replace('_', '').isalnum() or parsed.path not in ('', '/')):
        raise RuntimeError('Refused unsafe child integration target')
    with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
        db = client[database]
        if client.admin.command('hello').get('setName') != 'msIntegration' or not db['_integration_manifest'].find_one({
                '_id': 'isolation', 'synthetic': True, 'purpose': 'disposable-synthetic-integration'}):
            raise RuntimeError('Refused missing isolation manifest')
        repo = ResearchRepository(db)
        if repo.detail(study_id)['source'] != 'tiktok':
            raise RuntimeError('Refused unrelated study')
        with BrowserSource().installed():
            ResearchWorker(repo, TikTokConnector(), after_stage=lambda: os._exit(71)).tick()
    raise RuntimeError('Expected worker interruption did not occur')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uri', required=True)
    parser.add_argument('--database', default='media_scraper_integration_tiktok_' + uuid4().hex[:12])
    parser.add_argument('--confirm-isolated', required=True, action='store_true')
    parser.add_argument('--child-study', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child_study:
        return child_stage(args.uri, args.database, args.child_study)
    context = Context(args.uri, args.database, 'msIntegration')
    TikTokMongoFlow.context = context
    try:
        print(json.dumps({'environment': context.environment, 'source_content': 'controlled fixtures',
                          'external_acquisition': False}), flush=True)
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TikTokMongoFlow))
        print(json.dumps({'reports': context.reports, 'tests_run': result.testsRun,
                          'failures': len(result.failures), 'errors': len(result.errors)}), flush=True)
        return 0 if result.wasSuccessful() else 1
    finally:
        context.client.close()


if __name__ == '__main__':
    raise SystemExit(main())
