"""Permission-gated thematic UI adapter over the active TikTok Playwright engine.

Local checkpoints verify an observed prefix; they are NOT TikTok API cursors.
No direct calls to internal endpoints, stealth or challenge handling are added.
"""
import asyncio
import hashlib
import json
import os
import time
from urllib.parse import urlsplit, parse_qs

from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from .reference_runtime import (AccessRestricted, IdentityError, publication_url,
    persistent_playwright, validate_access, metric_dict, verified_publication)
from .session import SessionBusyError
from .vendor.scrapingtiktok.tiktok_scraper import TikTokScraper
from .research_sources import Page, SourceFailure
from .research_diagnostics import event, stage, diagnose, observe, SELECTORS, ObservedContext
from .research_tiktok_browser import browser_headless, navigate_search, install_search_signals, SEARCH_WAIT_UNTIL

VERSION = 'tiktok-ui-prefix-v1'


class AcquisitionAccessEvidence:
    """Only target-page/target-comments denials establish an HTTP access gate."""
    def __init__(self, video_id):
        self.video_id = video_id
        self.confirmed = []
        self.confirmed_count = 0
        self.secondary_http_errors = 0
        self.target_load_errors = 0
        self.snapshots = {}

    def confirm(self, reason, **fields):
        self.confirmed_count += 1
        evidence = {'reason': reason, **fields}
        if len(self.confirmed) < 10:
            self.confirmed.append(evidence)
        event('acquisition_access_evidence', **evidence)

    def attach(self, page):
        def response_seen(response):
            if response.status < 400:
                return
            request = response.request
            parsed = urlsplit(response.url)
            target_origin = parsed.scheme == 'https' and parsed.hostname in ('www.tiktok.com', 'tiktok.com')
            main_document = request.resource_type == 'document' and response.frame == page.main_frame
            target_comments = (target_origin and request.resource_type in ('xhr', 'fetch')
                and request.frame == page.main_frame and parsed.path.rstrip('/') == '/api/comment/list'
                and parse_qs(parsed.query).get('aweme_id') == [self.video_id])
            if response.status in (401, 403, 429) and (main_document or target_comments):
                self.confirm('http_main_document' if main_document else 'http_target_comments',
                             http_status=response.status)
            else:
                if main_document or target_comments:
                    self.target_load_errors += 1
                else:
                    self.secondary_http_errors += 1
                # No resource URL, query, payload, headers or response body.
                event('acquisition_http_error', http_status=response.status,
                      scope='main_document' if main_document else 'target_comments' if target_comments else 'other_response',
                      establishes_access_restriction=False)
        page.on('response', response_seen)

    def diagnostic(self, code, summary):
        self.snapshots['before' if code == 'publication_document_loaded' else 'after'] = {
            key: summary[key] for key in ('classification', 'http_status', 'ready_state',
                'browser_errors', 'video_json_present')}
        if summary['classification'] in ('authentication', 'captcha_or_verification'):
            self.confirm(summary['classification'], phase=code)

    def report(self, *, engine_guard=False, observed_comments=None):
        event('acquisition_access_decision', restriction_confirmed=bool(self.confirmed_count or engine_guard),
              engine_access_guard=engine_guard, confirmed_evidence=self.confirmed,
              confirmed_evidence_count=self.confirmed_count,
              secondary_http_errors=self.secondary_http_errors, target_load_errors=self.target_load_errors, snapshots=self.snapshots,
              observed_comments=observed_comments)


async def wait_for_search_results(page, status, deadline, *, previous=None):
    """Poll the visual diagnostic's real video/JSON signals, not DOMContentLoaded.

    With previous results, a bounded scroll wait may expire without failing the
    batch. Initial unknown content gets the entire remaining discovery budget.
    """
    latest = None
    last_observation = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if previous is not None:
                return latest
            loading = (latest is None or latest['ready_state'] != 'complete'
                       or latest['loading_indicator'] or latest['load_problem_suspected'])
            raise SourceFailure('source_load_timeout' if loading else 'source_structure_changed', loading)
        try:
            async with asyncio.timeout(remaining):
                await validate_access(page)
                latest = await observe(page, status())
        except TimeoutError:
            if previous is not None:
                return latest
            raise SourceFailure('source_load_timeout', True) from None
        evidence = {key: latest[key] for key in ('classification', 'http_status', 'ready_state',
            'candidate_video_links', 'search_json_items', 'loading_indicator', 'browser_errors')}
        if evidence != last_observation:
            event('search_wait_state', **evidence)
            last_observation = evidence
        if latest['classification'] in ('authentication', 'captcha_or_verification', 'http_access_restricted'):
            raise AccessRestricted('restricted')
        if latest['classification'] == 'http_load_error':
            raise SourceFailure('source_load_timeout', True)
        location = urlsplit(page.url)
        if location.scheme != 'https' or location.hostname not in ('www.tiktok.com', 'tiktok.com') or location.path.rstrip('/') != '/search':
            raise AccessRestricted('unexpected_redirect')
        counts = (latest['candidate_video_links'], latest['search_json_items'] or 0)
        if latest['visible']['empty'] or (any(counts) and (previous is None or counts != previous)):
            return latest
        # Poll a condition with a deadline; the interval itself never declares readiness.
        await asyncio.sleep(min(0.2, max(0, deadline - time.monotonic())))


def external_acquisition_allowed():
    return os.getenv('MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED') == '1'


def canonical(url):
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.port is not None or parsed.fragment:
        raise IdentityError('invalid_publication')
    author, kind, identity = publication_url(url)
    if kind != 'video' or len(identity) > 24:
        raise IdentityError('invalid_publication')
    return f'https://www.tiktok.com/@{author.lower()}/video/{identity}'


def prefix(rows):
    # No usernames or comment payloads in the checkpoint.
    return hashlib.sha256(json.dumps([row.get('record_id', row['publication_id']) for row in rows],
                                    separators=(',', ':')).encode()).hexdigest()


def local_page(rows, *, kind, publication_id, cursor, limit, cap):
    try:
        state = json.loads(cursor) if cursor else {'v': 1, 'count': 0, 'digest': prefix([])}
        count = state['count']
        if (state['v'] != 1 or type(count) is not int or count < 0 or count >= cap
                or not isinstance(state['digest'], str) or prefix(rows[:count]) != state['digest']
                or len(rows) < count):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise SourceFailure('checkpoint_changed', False) from None
    end = min(count + limit, cap, len(rows))
    items = rows[count:end]
    next_cursor = json.dumps({'v': 1, 'count': end, 'digest': prefix(rows[:end])},
                            separators=(',', ':')) if end < min(len(rows), cap) else None
    return Page('tiktok', kind, publication_id, cursor, next_cursor, items, truncated=True)


class TikTokConnector:
    source = 'tiktok'

    def read(self, *, topic, config, kind, publication_id, cursor, limit, attempt):
        try:
            state = json.loads(cursor) if cursor else {'count': 0}
            count = state['count']
            if type(count) is not int or count < 0:
                raise ValueError()
            cap = config['max_publications'] if kind == 'discover' else config['max_comments_per_publication']
            if count >= cap:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise SourceFailure('checkpoint_changed', False) from None
        self.publication = None
        try:
            with stage('tiktok_batch', kind=kind, attempt=attempt):
                rows = asyncio.run(asyncio.wait_for(self.collect(topic, config, kind, publication_id,
                    min(count + limit + 1, cap)), timeout=config['batch_timeout_seconds']))
        except AccessRestricted:
            raise SourceFailure('access_restricted', False) from None
        except IdentityError:
            raise SourceFailure('invalid_provenance', False) from None
        except SessionBusyError:
            raise SourceFailure('session_busy', True) from None
        except TimeoutError:
            raise SourceFailure('source_load_timeout' if kind == 'discover' else 'browser_unavailable', True) from None
        except PlaywrightError:
            raise SourceFailure('browser_unavailable', True) from None
        page = local_page(rows, kind=kind, publication_id=publication_id, cursor=cursor, limit=limit, cap=cap)
        page.publication = self.publication
        return page

    async def collect(self, topic, config, kind, publication_id, wanted):
        # Availability/configuration is independent of permission for external I/O.
        if not external_acquisition_allowed():
            raise SourceFailure('source_permission_missing', False)
        headless = browser_headless()
        engine = TikTokScraper(headless=headless)
        started = time.monotonic()
        async with persistent_playwright(engine) as playwright:
            with stage('chromium_open', headless=headless):
                _, context = await engine._setup_context(playwright)
            if kind == 'discover':
                return await self.discover(context, topic, wanted, config['max_scrolls'],
                    timeout_seconds=max(0.01, config['batch_timeout_seconds'] - (time.monotonic() - started) - 1))
            url = canonical(publication_id)
            if url != publication_id:
                raise IdentityError('noncanonical_publication')
            author, _, video_id = publication_url(url)
            engine._profile_owner = {'uniqueId': author}
            access = AcquisitionAccessEvidence(video_id)
            observed_context = ObservedContext(context, on_page=access.attach, on_diagnostic=access.diagnostic)
            try:
                with stage('publication_and_comments_extraction', requested_comments=wanted):
                    raw = await engine._extract_single_video_details(observed_context, url, max_comments=wanted)
            except AccessRestricted:
                await observed_context.diagnose_open_pages('engine_access_restricted')
                access.report(engine_guard=True)
                raise
            event('comments_observed', received=len(raw.get('comments', [])), publication_verified=bool(raw.get('_verified')))
            access.report(observed_comments=len(raw.get('comments', [])))
            if access.confirmed_count:
                event('acquisition_batch_rejected', reason='confirmed_access_restriction',
                      observed_comments=len(raw.get('comments', [])), returned_comments=0)
                raise AccessRestricted('confirmed_access_restriction')
            if not raw.get('comments') and access.target_load_errors:
                # An unavailable comments response is not a successful empty video.
                raise SourceFailure('source_load_timeout', True)
            if not raw.get('_verified') or raw.get('video_id') != video_id:
                raise SourceFailure('source_structure_changed', False)
            self.publication = {'publication_id': url, 'description': raw.get('description', ''),
                'metrics': {target: raw[field] for target, field in (('views', 'views_count'), ('likes', 'likes_count'),
                ('comments_count', 'comments_count'), ('shares', 'shares_count'), ('saves', 'bookmarks_count'))
                if type(raw.get(field)) is int and raw[field] >= 0}}
            rows, seen = [], set()
            for comment in raw.get('comments', []):
                # DOM fallback has no stable ID: content fingerprint avoids using author identity.
                text = comment.get('text')
                identity = comment.get('comment_id')
                if not isinstance(text, str):
                    continue
                if not isinstance(identity, str) or not identity.isdigit():
                    identity = 'text-' + hashlib.sha256(text.encode()).hexdigest()
                if identity in seen:
                    continue
                seen.add(identity)
                rows.append({'record_id': identity, 'publication_id': url, 'text': text,
                    'acquisition_version': VERSION, 'record_kind': 'comment'})
            event('comments_processed', count=len(rows[:wanted]))
            return rows[:wanted]

    async def discover(self, context, topic, wanted, max_scrolls, *, timeout_seconds=45):
        page = await context.new_page()
        navigation = {'http_status': None, 'started': time.monotonic()}
        install_search_signals(page, navigation, prefix='search')
        started = time.perf_counter()
        deadline = time.monotonic() + timeout_seconds
        event('stage_started', stage='results_detection')
        try:
            with stage('search_navigation', wait_until=SEARCH_WAIT_UNTIL):
                try:
                    response = await navigate_search(page, topic,
                        timeout_ms=max(1, min(30000, (deadline-time.monotonic())*1000)))
                except PlaywrightTimeout:
                    if navigation['http_status'] is None:
                        raise SourceFailure('source_load_timeout', True) from None
                    # An HTTP response may arrive before DOMContentLoaded times out.
                    # Keep waiting for actual results within the original batch budget.
                    response = None
                    event('search_dom_load_pending', http_status=navigation['http_status'])
            with stage('document_inspection'):
                await diagnose(page, 'document_loaded', navigation['http_status'])
            if response and response.status in (401, 403, 429):
                raise AccessRestricted('restricted')
            await validate_access(page)
            location = urlsplit(page.url)
            if location.scheme != 'https' or location.hostname not in ('www.tiktok.com', 'tiktok.com') or location.path.rstrip('/') != '/search':
                raise AccessRestricted('unexpected_redirect')
            rows, known, authors, stalled = [], set(), {}, 0
            first_result = False
            previous = None
            for step in range(max_scrolls + 1):
                with stage('search_results_wait', scroll=step):
                    summary = await wait_for_search_results(page, lambda: navigation['http_status'],
                        deadline if step == 0 else min(deadline, time.monotonic() + 2), previous=previous)
                await validate_access(page)
                links = await page.locator(SELECTORS['candidate_links']).evaluate_all('(nodes) => nodes.slice(0, 1000).map(node => node.href)')
                metadata = {}
                script = page.locator('script#__UNIVERSAL_DATA_FOR_REHYDRATION__')
                if await script.count():
                    content = await script.first.text_content()
                    if content and len(content) < 2_000_000:
                        try:
                            data = json.loads(content).get('__DEFAULT_SCOPE__', {}).get('webapp.search', {})
                            for item in data.get('itemList', [])[:1000]:
                                author = item.get('author')
                                name = author.get('uniqueId') if isinstance(author, dict) else author
                                url = canonical(f'https://www.tiktok.com/@{name}/video/{item.get("id")}')
                                verified_publication(item, url, {'uniqueId': name})
                                stats = metric_dict(item)
                                metadata[url] = {'description': item.get('desc', ''), 'metrics': {
                                    target: stats[key] for target, key in (('views', 'playCount'), ('likes', 'diggCount'),
                                    ('comments_count', 'commentCount'), ('shares', 'shareCount'), ('saves', 'collectCount')) if key in stats}}
                        except (ValueError, AttributeError, TypeError, IdentityError):
                            raise SourceFailure('source_structure_changed', False) from None
                event('results_detected', scroll=step, candidate_links=len(links), metadata_publications=len(metadata), json_script_present=bool(await script.count()))
                before = len(rows)
                for link in [*links, *metadata]:
                    try:
                        url = canonical(link)
                    except (ValueError, IdentityError):
                        continue
                    author, _, video_id = publication_url(url)
                    if video_id in authors and authors[video_id] != author:
                        raise IdentityError('conflicting_publication_author')
                    if url in known:
                        continue
                    authors[video_id] = author
                    known.add(url)
                    rows.append({'publication_id': url, 'canonical_url': url, 'platform_id': video_id,
                        'author_handle': author, 'acquisition_version': VERSION, **metadata.get(url, {})})
                    if not first_result:
                        first_result = True
                        event('first_search_result', elapsed_seconds=round(time.perf_counter()-started, 4), valid_publications=len(rows))
                    if len(rows) >= wanted:
                        event('stage_finished', stage='results_detection', elapsed_seconds=round(time.perf_counter()-started, 4), valid_publications=len(rows))
                        return rows
                stalled = stalled + 1 if len(rows) == before else 0
                event('valid_videos_detected', scroll=step, valid_publications=len(rows))
                if stalled >= 2 or step == max_scrolls or time.monotonic() >= deadline or (summary and summary['visible']['empty']):
                    break
                previous = (summary['candidate_video_links'], summary['search_json_items'] or 0) if summary else previous
                await page.mouse.wheel(0, 1200)
            if not rows and not await page.locator('[data-e2e="search-empty"]').count():
                raise SourceFailure('source_structure_changed', False)
            event('stage_finished', stage='results_detection', elapsed_seconds=round(time.perf_counter()-started, 4), valid_publications=len(rows))
            return rows
        except BaseException as error:
            event('stage_failed', stage='results_detection', elapsed_seconds=round(time.perf_counter()-started, 4), error=error)
            await diagnose(page, error.code if isinstance(error, SourceFailure) else 'navigation_or_access_failure', navigation['http_status'])
            raise
        finally:
            await page.close()
