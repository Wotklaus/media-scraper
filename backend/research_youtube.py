"""YouTube Data API v3 adapter. No browser, SDK or author metadata retention."""
import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .research_sources import Page, SourceFailure

VIDEO = re.compile(r'^[A-Za-z0-9_-]{11}$')
VERSION = 'youtube-data-v3-v1'


def configured():
    return bool(os.getenv('YOUTUBE_API_KEY', '').strip())


class YouTubeConnector:
    source = 'youtube'

    def __init__(self, transport=None):
        self.transport = transport or self._http

    @staticmethod
    def _http(endpoint, params):
        key = os.getenv('YOUTUBE_API_KEY', '').strip()
        if not key:
            raise SourceFailure('credentials_missing', False)
        # Header avoids placing API keys in URLs. Never log requests or provider bodies.
        request = Request('https://www.googleapis.com/youtube/v3/' + endpoint + '?' + urlencode(params),
                          headers={'X-Goog-Api-Key': key, 'Accept': 'application/json'})
        try:
            with urlopen(request, timeout=10) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise SourceFailure('invalid_source_response', False)
                return json.loads(body)
        except HTTPError as error:
            try:
                reason = json.loads(error.read(8192)).get('error', {}).get('errors', [{}])[0].get('reason')
            except Exception:
                reason = None
            if reason in ('quotaExceeded', 'dailyLimitExceeded'):
                raise SourceFailure('quota_exceeded', False) from None
            if reason == 'commentsDisabled':
                raise SourceFailure('comments_disabled', False) from None
            if error.code == 429 or error.code >= 500:
                raise SourceFailure('provider_transient', True) from None
            raise SourceFailure('provider_access_denied', False) from None
        except (URLError, TimeoutError, OSError):
            raise SourceFailure('provider_transient', True) from None
        except (ValueError, TypeError):
            raise SourceFailure('invalid_source_response', False) from None

    def request(self, endpoint, **params):
        result = self.transport(endpoint, {k: v for k, v in params.items() if v is not None})
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            raise SourceFailure('invalid_source_response', False)
        token = result.get('nextPageToken')
        if token is not None and (not isinstance(token, str) or len(token) > 500 or not token):
            raise SourceFailure('invalid_source_response', False)
        return result

    def read(self, *, topic, config, kind, publication_id, cursor, limit, attempt):
        try:
            state = json.loads(cursor) if cursor else {}
            if not isinstance(state, dict) or cursor and state.get('v') != 1:
                raise ValueError()
            items, next_state = self._read(topic, config, kind, publication_id, state, limit)
            next_cursor = json.dumps({'v': 1, **next_state}, separators=(',', ':')) if next_state is not None else None
            count = (state.get('count', 0) + len(items)) if kind == 'discover' else state.get('count', 0) + 1
            cap = config['max_publications'] if kind == 'discover' else config['max_pages_per_publication']
            truncated = next_state is None and count >= cap
            return Page(self.source, kind, publication_id, cursor, next_cursor, items, truncated=truncated)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise SourceFailure('invalid_source_response', False) from None

    def _read(self, topic, config, kind, publication_id, state, limit):
        count = state.get('count', 0)
        if type(count) is not int or count < 0:
            raise ValueError()
        if kind == 'discover':
            remaining = config['max_publications'] - count
            if remaining <= 0:
                return [], None
            result = self.request('search', part='snippet', type='video', q=topic,
                maxResults=min(50, limit, remaining), pageToken=state.get('token'),
                publishedAfter=config.get('published_after'), publishedBefore=config.get('published_before'))
            ids = [item['id']['videoId'] for item in result['items']]
            if any(not isinstance(identity, str) or not VIDEO.fullmatch(identity) for identity in ids):
                raise ValueError()
            metadata = self.request('videos', part='snippet,statistics', id=','.join(ids)) if ids else {'items': []}
            items = []
            for video in metadata['items']:
                if video['id'] not in ids:
                    raise ValueError()
                stats = video.get('statistics', {})
                metrics = {name: int(stats[field]) for name, field in
                    (('views', 'viewCount'), ('likes', 'likeCount'), ('comments_count', 'commentCount'))
                    if field in stats and str(stats[field]).isdigit()}
                items.append({'publication_id': video['id'], 'description': video['snippet'].get('description', ''),
                    'title': video['snippet'].get('title', ''), 'published_at': video['snippet'].get('publishedAt'),
                    'metrics': metrics, 'acquisition_version': VERSION})
            count += len(ids)
            token = result.get('nextPageToken')
            return items, {'token': token, 'count': count} if token and count < config['max_publications'] else None
        if not isinstance(publication_id, str) or not VIDEO.fullmatch(publication_id):
            raise ValueError()
        if count >= config['max_pages_per_publication']:
            return [], None
        parent = state.get('parent')
        result = self.request('comments' if parent else 'commentThreads', part='snippet',
            **({'parentId': parent} if parent else {'videoId': publication_id, 'order': 'time'}),
            textFormat='plainText', maxResults=limit if parent or not config['include_replies'] else 1,
            pageToken=state.get('token'))
        items = []
        for item in result['items']:
            comment = item if parent else item['snippet']['topLevelComment']
            snippet = comment['snippet']
            if snippet.get('videoId', publication_id) != publication_id:
                raise ValueError()
            items.append({'record_id': comment['id'], 'publication_id': publication_id,
                'text': snippet.get('textOriginal', snippet.get('textDisplay')),
                'published_at': snippet.get('publishedAt'), 'record_kind': 'reply' if parent else 'comment',
                'acquisition_version': VERSION})
        count += 1
        token = result.get('nextPageToken')
        if parent:
            next_state = {'parent': parent, 'token': token, 'after': state.get('after'), 'count': count} if token else (
                {'token': state['after'], 'count': count} if state.get('after') else None)
        elif config['include_replies'] and result['items'] and result['items'][0]['snippet'].get('totalReplyCount', 0):
            next_state = {'parent': result['items'][0]['snippet']['topLevelComment']['id'],
                          'after': token, 'count': count}
        else:
            next_state = {'token': token, 'count': count} if token else None
        if count >= config['max_pages_per_publication']:
            next_state = None
        return items, next_state
