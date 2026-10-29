"""Research-only MongoDB persistence, fenced leases and two-phase page checkpoints.

Transactions require the same replica-set/Atlas support as the existing repository.
No method accesses the legacy collections. Connector calls never run in a transaction.
"""
from datetime import datetime, timedelta, timezone
from secrets import token_hex
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.write_concern import WriteConcern

from .research_models import ACTIVE, SOURCE_LABEL, Counters
from .research_privacy import prepare_record

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class ResearchMissing(LookupError):
    pass


class ResearchConflict(RuntimeError):
    pass


class LeaseLost(ResearchConflict):
    pass


class ResearchRepository:
    def __init__(self, database, clock=None):
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.studies = database['research_studies']
        self.tasks = database['research_tasks']
        self.publications = database['research_publications']
        self.records = database['research_records']

    def transaction(self, callback):
        with self.database.client.start_session() as session:
            return session.with_transaction(callback, write_concern=WriteConcern('majority'), max_commit_time_ms=10000)

    def ensure_indexes(self):
        self.studies.create_index([('status', 1), ('next_run_at', 1), ('lease_until', 1)])
        self.studies.create_index([('created_at', -1), ('_id', 1)])
        self.tasks.create_index([('study_id', 1), ('kind', 1), ('publication_id', 1)], unique=True)
        self.tasks.create_index([('study_id', 1), ('status', 1), ('next_attempt_at', 1)])
        self.publications.create_index([('study_id', 1), ('source', 1), ('publication_id', 1)], unique=True)
        self.records.create_index([('study_id', 1), ('record_key', 1)], unique=True)
        self.records.create_index([('study_id', 1), ('_id', 1)])

    def task_document(self, study_id, kind, publication_id=None):
        now = self.clock()
        return {'_id': str(uuid4()), 'study_id': study_id, 'kind': kind,
            'publication_id': publication_id, 'priority': 0 if kind == 'discover' else 1,
            'status': 'queued', 'cursor': None, 'offset': 0, 'last_checkpoint': None,
            'pending': None, 'attempts': 0, 'failures': 0, 'last_error': None,
            'updated_at': now, 'next_attempt_at': now, 'lease_owner': None, 'lease_until': EPOCH}

    def create(self, request):
        self.ensure_indexes()
        now, identity = self.clock(), str(uuid4())
        document = {'_id': identity, **request.model_dump(), 'synthetic': request.source == 'synthetic',
            'source_label': SOURCE_LABEL if request.source == 'synthetic' else ('YouTube Data API v3' if request.source == 'youtube' else 'TikTok · Playwright'), 'status': 'draft', 'created_at': now,
            'updated_at': now, 'last_error': None, 'stop_reason': None,
            'warnings': [SOURCE_LABEL if request.source == 'synthetic' else 'Cobertura limitada por disponibilidad, cuotas y límites configurados; el objetivo no está garantizado.', 'Preparación de identificadores directos; no garantiza anonimización irreversible.'],
            'counters': Counters().model_dump(), 'budget_used_seconds': 0.0,
            'dedup_secret': token_hex(32), 'lease_owner': None, 'lease_until': EPOCH, 'next_run_at': now}
        task = self.task_document(identity, 'discover')
        def save(session):
            self.studies.insert_one(document, session=session)
            self.tasks.insert_one(task, session=session)
        self.transaction(save)
        return self.detail(identity)

    def raw_study(self, identity, session=None):
        study = self.studies.find_one({'_id': identity}, session=session)
        if study is None:
            raise ResearchMissing('La investigación no existe.')
        return study

    def public_study(self, study):
        fields = ('topic', 'description', 'source', 'synthetic', 'source_label', 'target_records',
                  'status', 'limits', 'source_config', 'counters', 'created_at', 'updated_at',
                  'last_error', 'stop_reason', 'warnings')
        result = {key: study[key] for key in fields}
        result['study_id'] = study['_id']
        result['pending_tasks'] = self.tasks.count_documents({'study_id': study['_id'],
            'status': {'$in': ['queued', 'processing', 'retry_wait']}})
        result['failed_tasks'] = self.tasks.count_documents({'study_id': study['_id'], 'status': 'failed'})
        result['progress_percent'] = round(min(100, 100 * study['counters']['prepared'] / study['target_records']), 2)
        return result

    def detail(self, identity):
        return self.public_study(self.raw_study(identity))

    def list(self, offset=0, limit=20):
        rows = self.studies.find({}).sort([('created_at', -1), ('_id', 1)]).skip(offset).limit(limit)
        return {'studies': [self.public_study(row) for row in rows],
                'total': self.studies.count_documents({}), 'offset': offset, 'limit': limit}

    def control(self, identity, action):
        allowed = {'start': ('draft',), 'pause': ACTIVE, 'resume': ('paused',),
                   'cancel': ('draft', *ACTIVE, 'paused')}
        target = {'start': 'queued', 'pause': 'paused', 'resume': 'queued', 'cancel': 'cancelled'}
        now = self.clock()
        def apply(session):
            study = self.raw_study(identity, session)
            if study['status'] not in allowed[action]:
                raise ResearchConflict('La transición solicitada no está permitida en el estado actual.')
            fields = {'status': target[action], 'updated_at': now, 'lease_owner': None,
                      'lease_until': EPOCH, 'next_run_at': now, 'stop_reason': action}
            if action == 'resume':
                fields['budget_used_seconds'] = 0.0
            self.studies.update_one({'_id': identity}, {'$set': fields}, session=session)
            if action == 'cancel':
                self.tasks.update_many({'study_id': identity, 'status': {'$in': ['queued', 'processing', 'retry_wait']}},
                    {'$set': {'status': 'cancelled', 'lease_owner': None, 'lease_until': EPOCH, 'updated_at': now}}, session=session)
        self.transaction(apply)
        return self.detail(identity)

    def claim_study(self):
        now, owner = self.clock(), str(uuid4())
        query = {'status': {'$in': list(ACTIVE)}, 'next_run_at': {'$lte': now}, 'lease_until': {'$lte': now}}
        candidate = self.studies.find_one(query, sort=[('next_run_at', 1), ('created_at', 1), ('_id', 1)])
        if candidate is None:
            return None
        return self.studies.find_one_and_update({**query, '_id': candidate['_id']},
            {'$set': {'lease_owner': owner, 'lease_until': now + timedelta(seconds=candidate['limits']['lease_seconds'])}},
            return_document=ReturnDocument.AFTER)

    def guard(self, study, session):
        now = self.clock()
        current = self.studies.find_one_and_update({'_id': study['_id'],
            'lease_owner': study['lease_owner'], 'lease_until': {'$gt': now},
            'status': {'$in': list(ACTIVE)}}, {'$set': {'updated_at': now,
                'lease_until': now + timedelta(seconds=study['limits']['lease_seconds'])}},
            return_document=ReturnDocument.AFTER, session=session)
        if current is None:
            raise LeaseLost('La reserva ya no está vigente.')
        return current

    def next_task(self, study, session):
        """TikTok drains durable work before asking a live search for another prefix."""
        query = {'study_id': study['_id'], 'status': {'$in': ['queued', 'processing', 'retry_wait']}}
        order = [('priority', 1), ('publication_id', 1), ('_id', 1)]
        if study['source'] == 'tiktok':
            pending = self.tasks.find_one({**query, 'pending.done': {'$in': [True, False]}},
                                          sort=order, session=session)
            if pending is not None:
                return pending
            acquisition = self.tasks.find_one({**query, 'kind': 'acquire'}, sort=order, session=session)
            if acquisition is not None:
                return acquisition
        return self.tasks.find_one(query, sort=order if study['source'] == 'tiktok' else [('next_attempt_at', 1)], session=session)

    def claim_task(self, study):
        def claim(session):
            current = self.guard(study, session)
            query = {'study_id': study['_id'],
                'status': {'$in': ['queued', 'processing', 'retry_wait']}, 'next_attempt_at': {'$lte': self.clock()}}
            # Keep the existing scheduling for other providers.
            if study['source'] == 'tiktok':
                candidate = self.next_task(study, session)
                if candidate is None:
                    return None
                query['_id'] = candidate['_id']
            return self.tasks.find_one_and_update(query,
                {'$set': {'status': 'processing', 'lease_owner': study['lease_owner'],
                          'lease_until': current['lease_until'], 'updated_at': self.clock()},
                '$inc': {'attempts': 1}}, sort=[('priority', 1), ('publication_id', 1), ('_id', 1)],
                return_document=ReturnDocument.AFTER, session=session)
        return self.transaction(claim)

    def stage_page(self, study, task, page):
        """Atomically persist the bounded batch, counters and its pending checkpoint."""
        now = self.clock()
        def stage(session):
            current = self.guard(study, session)
            saved = self.tasks.find_one({'_id': task['_id'], 'lease_owner': study['lease_owner']}, session=session)
            if saved is None or saved['pending'] is not None:
                raise LeaseLost('El lote ya tiene una confirmación pendiente.')
            if page.publication is not None:
                metadata = page.publication
                if task['kind'] != 'acquire' or metadata.get('publication_id') != task['publication_id']:
                    raise ResearchConflict('Metadatos de otra publicación.')
                prepared_description = prepare_record({'record_id': 'description', 'publication_id': task['publication_id'],
                    'text': metadata.get('description')}, study['_id'], current['dedup_secret'], max_length=10000)
                self.publications.update_one({'study_id': study['_id'], 'publication_id': task['publication_id']},
                    {'$set': {'description': prepared_description['text'] if prepared_description else 'Sin descripción disponible',
                        'metrics': {key: value for key, value in metadata.get('metrics', {}).items()
                            if key in ('views', 'likes', 'comments_count', 'shares', 'saves') and type(value) is int and value >= 0}}}, session=session)
            counts = {'received': 0, 'prepared': 0, 'duplicates': 0, 'excluded': 0, 'publications_discovered': 0}
            consumed = task['offset']
            for index, item in enumerate(page.items[task['offset']:], task['offset']):
                if current['counters']['prepared'] + counts['prepared'] >= current['target_records']:
                    break
                consumed = index + 1
                if task['kind'] == 'discover':
                    identity = {'study_id': study['_id'], 'source': study['source'], 'publication_id': item['publication_id']}
                    description = prepare_record({'record_id': 'description', 'publication_id': item['publication_id'],
                        'text': item.get('description')}, study['_id'], current['dedup_secret'], max_length=10000)
                    metrics = item.get('metrics') if isinstance(item.get('metrics'), dict) else {}
                    result = self.publications.update_one(identity, {'$setOnInsert': {
                        **identity, 'synthetic': study['synthetic'],
                        'description': description['text'] if description else 'Sin descripción disponible',
                        'title': (prepare_record({'record_id': 'title', 'publication_id': item['publication_id'], 'text': item.get('title')}, study['_id'], current['dedup_secret']) or {}).get('text', ''),
                        'published_at': item.get('published_at'),
                        'acquisition_version': item.get('acquisition_version', 'synthetic-v1'),
                        **{key: item[key] for key in ('canonical_url', 'platform_id', 'author_handle') if key in item},
                        'metrics': {key: value for key, value in metrics.items()
                                    if key in ('views', 'likes', 'comments_count', 'shares', 'saves')
                                    and type(value) is int and value >= 0},
                        'discovered_at': now, 'processed': False}}, upsert=True, session=session)
                    if result.upserted_id is not None:
                        counts['publications_discovered'] += 1
                        self.tasks.insert_one(self.task_document(study['_id'], 'acquire', item['publication_id']), session=session)
                else:
                    counts['received'] += 1
                    prepared = prepare_record(item, study['_id'], current['dedup_secret'])
                    if prepared is None:
                        counts['excluded'] += 1
                        continue
                    prepared['synthetic'] = study['synthetic']
                    prepared.update(source=study['source'], published_at=item.get('published_at'),
                        record_kind=item.get('record_kind', 'comment'), acquisition_version=item.get('acquisition_version', 'synthetic-v1'))
                    identity = {'study_id': study['_id'], 'record_key': prepared['record_key']}
                    result = self.records.update_one(identity, {'$setOnInsert': {
                        '_id': str(uuid4()), **identity, **prepared, 'created_at': now}}, upsert=True, session=session)
                    counts['prepared' if result.upserted_id is not None else 'duplicates'] += 1
            target = current['counters']['prepared'] + counts['prepared'] >= current['target_records']
            fully_consumed = consumed == len(page.items)
            checkpoint = {'cursor': page.next_cursor if fully_consumed else page.cursor,
                          'offset': 0 if fully_consumed else consumed,
                          'done': fully_consumed and page.next_cursor is None or target,
                          'source_complete': fully_consumed and page.next_cursor is None and not page.truncated}
            self.tasks.update_one({'_id': task['_id'], 'lease_owner': study['lease_owner']},
                {'$set': {'pending': checkpoint, 'updated_at': now}}, session=session)
            self.studies.update_one({'_id': study['_id']}, {'$inc': {
                **{f'counters.{key}': value for key, value in counts.items()},
                'counters.batches': 1}, '$set': {
                'status': 'discovering' if task['kind'] == 'discover' else 'acquiring', 'updated_at': now}}, session=session)
            return counts
        return self.transaction(stage)

    def confirm_page(self, study, task):
        now = self.clock()
        def confirm(session):
            current = self.guard(study, session)
            saved = self.tasks.find_one({'_id': task['_id'], 'lease_owner': study['lease_owner']}, session=session)
            if saved is None or saved['pending'] is None:
                raise LeaseLost('No hay un checkpoint pendiente bajo esta reserva.')
            pending = saved['pending']
            self.tasks.update_one({'_id': task['_id']}, {'$set': {
                'cursor': pending['cursor'], 'offset': pending['offset'], 'pending': None,
                'status': 'completed' if pending['done'] else 'queued', 'last_checkpoint': now,
                'updated_at': now, 'lease_owner': None, 'lease_until': EPOCH,
                'failures': 0, 'last_error': None}}, session=session)
            if current['source'] == 'tiktok':
                self.studies.update_one({'_id': study['_id']},
                    {'$set': {'last_error': None, 'stop_reason': None}}, session=session)
            if pending['done'] and task['kind'] == 'acquire':
                self.publications.update_one({'study_id': study['_id'], 'publication_id': task['publication_id']},
                    {'$set': {'processed': True, 'source_complete': pending['source_complete']}}, session=session)
                self.studies.update_one({'_id': study['_id']}, {'$inc': {'counters.publications_processed': 1}}, session=session)
            if current['counters']['prepared'] >= current['target_records']:
                self.studies.update_one({'_id': study['_id']}, {'$set': {'status': 'target_reached', 'stop_reason': 'target_reached'}}, session=session)
                self.tasks.update_many({'study_id': study['_id'], 'status': {'$in': ['queued', 'processing', 'retry_wait']}},
                    {'$set': {'status': 'cancelled', 'updated_at': now}}, session=session)
        self.transaction(confirm)

    def fail_task(self, study, task, code, retryable=True):
        now = self.clock()
        def fail(session):
            self.guard(study, session)
            failures = task['failures'] + 1
            blocked = code in ('quota_exceeded', 'credentials_missing', 'provider_access_denied', 'source_permission_missing', 'access_restricted', 'checkpoint_changed', 'source_structure_changed')
            retry = blocked or retryable and failures < study['limits']['max_attempts']
            self.tasks.update_one({'_id': task['_id'], 'lease_owner': study['lease_owner']},
                {'$set': {'status': 'retry_wait' if retry else 'failed', 'last_error': code,
                    'failures': failures, 'updated_at': now, 'lease_until': EPOCH, 'lease_owner': None,
                    'next_attempt_at': now + timedelta(seconds=min(30, 2 ** failures))}}, session=session)
            self.studies.update_one({'_id': study['_id']}, {'$set': {'last_error': code, 'updated_at': now,
                    **({'status': 'paused', 'stop_reason': code} if blocked else {})}}, session=session)
        self.transaction(fail)

    def release(self, study, elapsed=0.0):
        """Reconcile after each page. A control request can revoke this lease at any time."""
        now = self.clock()
        def release(session):
            current = self.studies.find_one({'_id': study['_id'], 'lease_owner': study['lease_owner']}, session=session)
            if current is None:
                return
            fields = {'lease_owner': None, 'lease_until': EPOCH, 'updated_at': now, 'next_run_at': now}
            if current['status'] in ACTIVE:
                next_task = self.next_task(current, session)
                if next_task is None:
                    failures = self.tasks.count_documents({'study_id': study['_id'], 'status': 'failed'}, session=session)
                    fields['status'] = ('partial' if current['counters']['prepared'] else 'failed') if failures else 'exhausted'
                    fields['stop_reason'] = 'task_failures' if failures else 'source_exhausted'
                elif current['budget_used_seconds'] + elapsed >= current['limits']['time_budget_seconds']:
                    fields.update(status='paused', stop_reason='time_budget_reached')
                else:
                    fields['next_run_at'] = next_task['next_attempt_at']
            self.studies.update_one({'_id': study['_id'], 'lease_owner': study['lease_owner']},
                {'$set': fields, '$inc': {'counters.processing_seconds': elapsed, 'budget_used_seconds': elapsed}}, session=session)
        self.transaction(release)

    def record_page(self, identity, offset=0, limit=50):
        self.raw_study(identity)
        fields = ('publication_id', 'text', 'synthetic', 'privacy_version', 'redactions', 'created_at')
        rows = self.records.find({'study_id': identity}).sort('_id', 1).skip(offset).limit(limit)
        return {'records': [{'record_id': row['_id'], **{key: row[key] for key in fields}, **{key: row[key] for key in ('source', 'published_at', 'record_kind', 'acquisition_version') if key in row}} for row in rows],
                'total': self.records.count_documents({'study_id': identity}), 'offset': offset, 'limit': limit, 'source_label': self.raw_study(identity)['source_label']}

    def task_page(self, identity, offset=0, limit=50):
        self.raw_study(identity)
        fields = ('kind', 'publication_id', 'status', 'cursor', 'offset', 'last_checkpoint',
                  'attempts', 'failures', 'last_error', 'updated_at', 'lease_until')
        rows = self.tasks.find({'study_id': identity}).sort('_id', 1).skip(offset).limit(limit)
        return {'tasks': [{'task_id': row['_id'], 'pending_confirmation': row['pending'] is not None,
                          **{key: row[key] for key in fields}} for row in rows],
                'total': self.tasks.count_documents({'study_id': identity}), 'offset': offset, 'limit': limit}

    def publication_page(self, identity, offset=0, limit=50):
        self.raw_study(identity)
        rows = self.publications.find({'study_id': identity}, {'_id': 0, 'study_id': 0}).sort('publication_id', 1).skip(offset).limit(limit)
        return {'publications': list(rows), 'total': self.publications.count_documents({'study_id': identity}),
                'offset': offset, 'limit': limit}
