"""TikTok UI fixtures only. All browser requests intercepted; no external scraping."""
import asyncio
from contextlib import asynccontextmanager
import json
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
from urllib.parse import urlsplit

from playwright.async_api import async_playwright
from pydantic import ValidationError

from backend.research_models import StudyCreate, StudyResponse
from backend.research_repository import ResearchRepository
from backend.research_sources import SourceFailure, source_capabilities
from backend.research_tiktok import TikTokConnector, canonical, local_page, prefix
from backend.research_worker import ResearchWorker
from backend.reference_runtime import SharedBrowser, IdentityError
from backend.vendor.scrapingtiktok import tiktok_scraper as original
from research_fake import Database, Clock
from test_research import drain

URL = 'https://www.tiktok.com/@example/video/333'
PERMISSION = {'MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED': '1'}


def rows(size):
    return [{'publication_id': URL, 'record_id': str(index), 'text': f'Pregunta {index} contacto persona@example.invalid @lector'} for index in range(size)]


class TikTokContractsTests(unittest.TestCase):
    def test_selection_available_without_external_permission_and_config_limits(self):
        with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED': ''}), patch('backend.research_tiktok.persistent_playwright') as browser:
            self.assertTrue(source_capabilities()[2]['available'])
            with self.assertRaises(SourceFailure) as caught:
                asyncio.run(TikTokConnector().collect('tema', {}, 'discover', None, 50))
            self.assertEqual(caught.exception.code, 'source_permission_missing'); browser.assert_not_called()
        with patch.dict('os.environ', PERMISSION):
            self.assertTrue(source_capabilities()[2]['available'])
        for values in ({'limits': {'lease_seconds': 20}}, {'source_config': {'max_publications': 201}},
                       {'source_config': {'max_comments_per_publication': 2001}}):
            with self.assertRaises(ValidationError):
                StudyCreate(topic='libre', source='tiktok', **values)

    def test_local_read_without_any_acquisition_environment(self):
        config = StudyCreate(topic='tema', source='tiktok').source_config.model_dump()
        with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED': ''}), patch.object(TikTokConnector, 'collect', new_callable=AsyncMock, return_value=[{'publication_id': URL}]) as collect:
            result = TikTokConnector().read(topic='tema', config=config, kind='discover', publication_id=None, cursor=None, limit=50, attempt=1)
            self.assertEqual(result.items, [{'publication_id': URL}]); collect.assert_awaited_once()

    def test_api_create_start_and_worker_pauses_before_external_browser(self):
        from backend import research_routes
        from test_embeddings import request
        config = {'topic': 'tema libre', 'source': 'tiktok', 'target_records': 600}
        database = Database()
        with patch.dict('os.environ', {'MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED': ''}), patch.object(research_routes, 'get_database', return_value=database), patch('backend.research_tiktok.persistent_playwright') as browser:
            status, capabilities = asyncio.run(request('GET', '/api/research/sources'))
            self.assertEqual(status, 200)
            self.assertTrue(next(item for item in capabilities['sources'] if item['source'] == 'tiktok')['available'])
            status, study = asyncio.run(request('POST', '/api/research/studies', body=json.dumps(config).encode()))
            self.assertEqual(status, 201); self.assertEqual(study['status'], 'draft')
            status, study = asyncio.run(request('POST', f'/api/research/studies/{study["study_id"]}/start'))
            self.assertEqual(status, 202); self.assertEqual(study['status'], 'queued')
            browser.assert_not_called()
            repository = ResearchRepository(database)
            ResearchWorker(repository).tick()
            result = repository.detail(study['study_id'])
            self.assertEqual(result['status'], 'paused')
            self.assertEqual(result['last_error'], 'source_permission_missing')
            self.assertEqual(result['counters']['prepared'], 0)
            browser.assert_not_called()

    def test_urls_reject_foreign_credentials_ports_and_photos(self):
        self.assertEqual(canonical(URL + '?tracking=1'), URL)
        for url in ('https://evil.invalid/@example/video/333', 'http://www.tiktok.com/@example/video/333',
                    'https://u:p@www.tiktok.com/@example/video/333', URL + '#x',
                    'https://www.tiktok.com:443/@example/video/333', 'https://www.tiktok.com/@example/photo/333'):
            with self.assertRaises((IdentityError, ValueError)):
                canonical(url)

    def test_local_checkpoints_are_prefix_verified_not_server_cursors(self):
        page = local_page(rows(11), kind='acquire', publication_id=URL, cursor=None, limit=5, cap=100)
        self.assertTrue(page.truncated)
        self.assertNotIn('persona', page.next_cursor)
        next_page = local_page(rows(11), kind='acquire', publication_id=URL, cursor=page.next_cursor, limit=5, cap=100)
        self.assertEqual(next_page.items[0]['record_id'], '5')
        changed = rows(11); changed[0]['record_id'] = 'new-first'
        for cursor, sample in ((page.next_cursor, changed), ('opaque-tiktok-token', rows(11)), (page.next_cursor, [])):
            with self.assertRaises(SourceFailure):
                local_page(sample, kind='acquire', publication_id=URL, cursor=cursor, limit=5, cap=100)

    def test_controlled_400_600_1000_interruption_and_privacy(self):
        class Controlled(TikTokConnector):
            async def collect(self, topic, config, kind, publication_id, wanted):
                if kind == 'discover':
                    return [{'publication_id': URL, 'canonical_url': URL, 'platform_id': '333', 'author_handle': 'example'}]
                self.publication = {'publication_id': URL, 'description': 'Descripción @lector', 'metrics': {'views': 123}}
                return rows(wanted)
        with patch.dict('os.environ', PERMISSION):
            for target in (400, 600, 1000):
                clock = Clock(); repo = ResearchRepository(Database(), clock)
                identity = repo.create(StudyCreate(topic='Área libre Ω', source='tiktok', target_records=target,
                    source_config={'max_comments_per_publication': 1200}))['study_id']
                repo.control(identity, 'start')
                def crash(): raise SystemExit('controlled interruption')
                with self.assertRaises(SystemExit): ResearchWorker(repo, Controlled(), crash).tick()
                clock.advance(61)
                result = drain(repo, identity, clock, ResearchWorker(repo, Controlled()))
                self.assertEqual(result['counters']['prepared'], target)
                self.assertEqual(result['status'], 'target_reached')
                self.assertFalse(StudyResponse.model_validate(result).synthetic)
                self.assertNotIn('persona@example.invalid', str(repo.record_page(identity)))
                self.assertEqual(repo.publication_page(identity)['publications'][0]['metrics']['views'], 123)

    def test_restriction_pauses_worker_without_losing_checkpoint(self):
        class Restricted:
            def read(self, **kwargs): raise SourceFailure('access_restricted', False)
        clock = Clock(); repo = ResearchRepository(Database(), clock)
        identity = repo.create(StudyCreate(topic='Tema', source='tiktok'))['study_id']; repo.control(identity, 'start')
        ResearchWorker(repo, Restricted()).tick()
        self.assertEqual(repo.detail(identity)['status'], 'paused')
        self.assertFalse(ResearchWorker(repo, Restricted()).tick())


class TikTokBrowserTests(unittest.TestCase):
    def execute(self, mode='normal', kind='discover'):
        async def scenario():
            engine_contexts = []
            async def setup(engine, playwright):
                browser = await playwright.chromium.launch(headless=True)
                context = await browser.new_context()
                engine._shared_context = context
                engine_contexts.append((context, browser))
                async def route_request(route):
                    path = urlsplit(route.request.url).path
                    if mode == 'blocked':
                        await route.fulfill(status=403, body='Restricted'); return
                    if mode == 'captcha':
                        await route.fulfill(content_type='text/html', body='<div id="captcha-visible">Stop</div>'); return
                    if path == '/api/comment/list/':
                        await route.fulfill(json={'status_code': 0, 'aweme_id': '333', 'comments': [
                            {'cid': '55', 'aweme_id': '333', 'text': 'Pregunta @lector', 'user': {'unique_id': 'reader'}},
                            {'cid': '55', 'aweme_id': '333', 'text': 'Pregunta @lector', 'user': {'unique_id': 'reader'}},
                            {'cid': '66', 'aweme_id': '444', 'text': 'foreign', 'user': {'unique_id': 'reader'}}]}); return
                    if path == '/search':
                        if mode == 'empty': body = '<div data-e2e="search-empty">Sin resultados</div>'
                        elif mode == 'changed': body = '<div>Unknown new structure</div>'
                        elif mode == 'dynamic':
                            body = '<main id="results"><a href="' + URL + '">Video</a></main><script>addEventListener("wheel",()=>{document.querySelector("main").insertAdjacentHTML("beforeend",\'<a href="https://www.tiktok.com/@second/video/444">Next</a>\')},{once:true})</script>'
                        else:
                            item = {'id': '333', 'author': {'uniqueId': 'example'}, 'desc': 'Tema descripción', 'stats': {'playCount': 123}}
                            body = '<main><a href="'+ URL +'">Video</a><a href="'+ URL +'?tracking=1">Duplicate</a><a href="https://evil.invalid/@x/video/1">Foreign</a></main><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'+json.dumps({'__DEFAULT_SCOPE__': {'webapp.search': {'itemList': [item]}}})+'</script>'
                    else:
                        item = {'id': '333', 'author': {'uniqueId': 'wrong' if mode == 'foreign' else 'example'}, 'desc': 'Descripción real simulada', 'stats': {'playCount': 123, 'diggCount': 4}}
                        body = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'+json.dumps({'__DEFAULT_SCOPE__': {'webapp.video-detail': {'itemInfo': {'itemStruct': item}}}})+'</script><button data-e2e="comment-icon" onclick="fetch(\'/api/comment/list/?aweme_id=333\')">Comments</button>'
                    await route.fulfill(content_type='text/html', body=body)
                await context.route('**/*', route_request)
                shared = SharedBrowser(context)
                return shared, await shared.new_context()
            @asynccontextmanager
            async def runtime(engine):
                async with async_playwright() as playwright:
                    try: yield playwright
                    finally:
                        for context, browser in engine_contexts:
                            await context.close(); await browser.close()
            with patch.dict('os.environ', PERMISSION), patch('backend.research_tiktok.persistent_playwright', runtime), patch.object(original.TikTokScraper, '_setup_context', setup), patch.object(original, 'asyncio', SimpleNamespace(sleep=AsyncMock())):
                connector = TikTokConnector()
                config = StudyCreate(topic='x', source='tiktok').source_config.model_dump()
                if mode == 'changed': config['batch_timeout_seconds'] = 2
                result = await connector.collect('Tema libre Ω', config, kind, URL if kind == 'acquire' else None, 2)
                if kind == 'acquire': self.assertEqual(connector.publication['metrics']['views'], 123)
                return result
        return asyncio.run(scenario())

    def test_discovery_rehydration_dedup_and_dynamic_scroll(self):
        result = self.execute()
        self.assertEqual(len(result), 1); self.assertEqual(result[0]['platform_id'], '333')
        self.assertEqual(result[0]['metrics']['views'], 123)
        self.assertEqual(len(self.execute('dynamic')), 2)

    def test_empty_changed_structure_and_access_restrictions(self):
        from backend.reference_runtime import AccessRestricted
        self.assertEqual(self.execute('empty'), [])
        with self.assertRaises(SourceFailure): self.execute('changed')
        for mode in ('blocked', 'captcha'):
            with self.assertRaises(AccessRestricted): self.execute(mode)

    def test_existing_engine_extracts_verified_metadata_and_network_comments(self):
        result = self.execute(kind='acquire')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['record_id'], '55')
        self.assertNotIn('username', str(result))
        with self.assertRaises(IdentityError): self.execute('foreign', kind='acquire')
