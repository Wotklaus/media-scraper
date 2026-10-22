"""Transactional persistence of real extractions; never invokes the scraper."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

from pymongo.write_concern import WriteConcern

from .database import get_database
from .normalizer import normalize_profile


class PersistenceError(RuntimeError):
    """Safe public error: underlying driver messages may contain credentials."""


PERSISTENCE_FAILURE = (
    "La extracción terminó, pero no se pudo confirmar su guardado en MongoDB. "
    "Comprueba la configuración y disponibilidad de la base de datos."
)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _comment_key(comment):
    if comment['comment_id'] is not None:
        return 'cid:' + comment['comment_id']
    # DOM comments have no TikTok ID. Do not invent one or deduplicate globally.
    return 'dom:' + _digest([comment['username'].casefold(), comment['text']])


class ProfileRepository:
    def __init__(self, database):
        if database.name != 'media_scraper':
            raise PersistenceError(PERSISTENCE_FAILURE)
        self.database = database

    def ensure_indexes(self):
        self.database['profiles'].create_index('username_key', unique=True, name='profile_username_unique')
        self.database['publications'].create_index('publication_id', unique=True, name='publication_id_unique')
        self.database['comments'].create_index(
            [('publication_id', 1), ('identity_key', 1)], unique=True, name='publication_comment_unique')
        self.database['extraction_runs'].create_index('run_id', unique=True, name='extraction_run_unique')
        self.database['extraction_runs'].create_index([('profile_username_key', 1), ('extracted_at', -1)])

    def save(self, documents, *, run_id=None):
        """One immutable run per ID; retries of the same payload are idempotent.

        A new query receives a new run ID, even if its results are identical.
        Current documents contain the latest observation; run snapshots retain
        earlier metrics, warnings and recovered comments. No deletes are issued.
        """
        snapshot = deepcopy(documents)
        if snapshot['extraction_metadata']['mode'] != 'real':
            raise ValueError('Only real extractions can be persisted.')
        run_id = str(uuid4()) if run_id is None else run_id
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError('Extraction run ID must be a nonempty string.')
        extracted_at = datetime.now(timezone.utc)
        username_key = snapshot['profile']['username'].casefold()
        stable = deepcopy(snapshot)
        stable['extraction_metadata'].pop('normalized_at', None)
        fingerprint = _digest(stable)
        self.ensure_indexes()  # Outside the transaction, also initializes collections.

        def persist(session):
            runs = self.database['extraction_runs']
            existing = runs.find_one({'run_id': run_id}, session=session)
            if existing is not None:
                if existing['payload_hash'] != fingerprint:
                    raise PersistenceError(PERSISTENCE_FAILURE)
                return run_id
            seen = {'last_seen_at': extracted_at, 'last_run_id': run_id}
            self.database['profiles'].update_one(
                {'username_key': username_key},
                {'$set': {**snapshot['profile'], 'username_key': username_key, **seen},
                 '$setOnInsert': {'first_seen_at': extracted_at}}, upsert=True, session=session)
            for publication in snapshot['publications']:
                self.database['publications'].update_one(
                    {'publication_id': publication['publication_id']},
                    {'$set': {**publication, **seen}, '$setOnInsert': {'first_seen_at': extracted_at}},
                    upsert=True, session=session)
            for comment in snapshot['comments']:
                identity_key = _comment_key(comment)
                self.database['comments'].update_one(
                    {'publication_id': comment['publication_id'], 'identity_key': identity_key},
                    {'$set': {**comment, 'identity_key': identity_key, **seen},
                     '$setOnInsert': {'first_seen_at': extracted_at}}, upsert=True, session=session)
            runs.update_one(
                {'run_id': run_id}, {'$setOnInsert': {
                    'run_id': run_id, 'profile_username_key': username_key,
                    'extracted_at': extracted_at, 'payload_hash': fingerprint,
                    'snapshot': snapshot, 'status': 'saved',
                }}, upsert=True, session=session)
            return run_id

        with self.database.client.start_session() as session:
            return session.with_transaction(
                persist, write_concern=WriteConcern('majority'), max_commit_time_ms=10000)


def save_profile(profile):
    """Normalize and persist a real result, keeping credentials out of errors."""
    database = None
    try:
        documents = normalize_profile(profile)
        if documents['extraction_metadata']['mode'] != 'real':
            raise ValueError('Only real extractions can be persisted.')
        database = get_database()
        return ProfileRepository(database).save(documents)
    except Exception:
        raise PersistenceError(PERSISTENCE_FAILURE) from None
    finally:
        if database is not None:
            try:
                database.client.close()
            except Exception:
                pass  # Cleanup must not expose driver details or mask the outcome.
