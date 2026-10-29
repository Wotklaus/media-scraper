"""Bounded connector contract and deterministic data with no external I/O."""
from dataclasses import dataclass
from typing import Protocol


class SourceFailure(RuntimeError):
    def __init__(self, code='source_unavailable', retryable=True):
        self.code, self.retryable = code, retryable
        super().__init__(code)


@dataclass
class Page:
    source: str
    kind: str
    publication_id: str | None
    cursor: str | None
    next_cursor: str | None
    items: list[dict]


class Connector(Protocol):
    def read(self, *, topic: str, config: dict, kind: str, publication_id: str | None,
             cursor: str | None, limit: int, attempt: int) -> Page: ...


class SyntheticConnector:
    """Generates one page, never a full corpus. Topics are uninterpreted free text."""
    source = 'synthetic'
    def read(self, *, topic, config, kind, publication_id, cursor, limit, attempt):
        start = int(cursor or '0')
        if config['failure_stage'] == kind and start == 0 and (kind == 'discover' or publication_id == 'synthetic-video-00000') and (
                config['failure_mode'] == 'permanent' or
                config['failure_mode'] == 'transient' and attempt == 1):
            raise SourceFailure('synthetic_failure', config['failure_mode'] != 'permanent')
        total = config['publications'] if kind == 'discover' else config['comments_per_publication']
        end = min(start + limit, total)
        items = []
        for index in range(start, end):
            if kind == 'discover':
                items.append({'publication_id': f'synthetic-video-{index:05d}',
                    'description': f'Publicación de prueba {index}: {topic}',
                    'metrics': {'views': 100 + index, 'likes': index}})
            else:
                base = index - 1 if index % 10 == 1 else index
                items.append({'record_id': f'synthetic-comment-{base}', 'publication_id': publication_id,
                    'text': None if base % 17 == 0 else
                        f'Comentario de prueba {base}: {topic}. Contacto prueba@example.invalid @lector +593 99 123 4567.',
                    'username': 'synthetic_person', 'name': 'Nombre de prueba',
                    'avatar_url': 'https://fixture.invalid/avatar', 'profile_url': 'https://fixture.invalid/user'})
        return Page('synthetic', kind, publication_id, cursor,
                    str(end) if end < total else None, items)


def connector_for(source):
    # Only this registry and the source contracts need extending for an authorised source.
    factories = {'synthetic': SyntheticConnector}
    if source not in factories:
        raise SourceFailure('source_unavailable', False)
    return factories[source]()


def validate_page(page, task, limit, source='synthetic'):
    if (not isinstance(page, Page) or page.source != source or page.kind != task['kind']
            or page.publication_id != task['publication_id'] or page.cursor != task['cursor']
            or not isinstance(page.items, list) or len(page.items) > limit
            or page.next_cursor is not None and (not isinstance(page.next_cursor, str)
                or not page.next_cursor or len(page.next_cursor) > 2000 or page.next_cursor == page.cursor)):
        raise SourceFailure('invalid_provenance', False)
    for item in page.items:
        if (not isinstance(item, dict) or not isinstance(item.get('publication_id'), str)
                or not item['publication_id'].strip()
                or len(item['publication_id']) > 100
                or task['kind'] == 'acquire' and item['publication_id'] != task['publication_id']):
            raise SourceFailure('invalid_provenance', False)
