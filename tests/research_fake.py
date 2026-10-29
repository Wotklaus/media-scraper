"""Small transactional Mongo double. Never creates clients, sockets or files.

Models the operators exercised by research, unique indexes and rollback; it does
not claim to reproduce MongoDB's distributed transaction/replica-set behavior.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading
from types import SimpleNamespace

from pymongo.errors import DuplicateKeyError


def value(row, key):
    for part in key.split('.'):
        row = row.get(part) if isinstance(row, dict) else None
    return row


def matches(row, query):
    for key, expected in query.items():
        actual = value(row, key)
        if isinstance(expected, dict):
            for op, operand in expected.items():
                if op == '$in' and actual not in operand:
                    return False
                if op == '$lte' and (actual is None or actual > operand):
                    return False
                if op == '$gt' and (actual is None or actual <= operand):
                    return False
        elif actual != expected:
            return False
    return True


def set_value(row, key, val):
    parts = key.split('.')
    for part in parts[:-1]:
        row = row.setdefault(part, {})
    row[parts[-1]] = deepcopy(val)


def project(row, projection):
    if not projection:
        return deepcopy(row)
    if any(projection.values()):
        return {k: deepcopy(v) for k, v in row.items() if projection.get(k) or k == '_id' and projection.get('_id', 1)}
    return {k: deepcopy(v) for k, v in row.items() if projection.get(k, 1)}


class Cursor:
    def __init__(self, rows, projection=None):
        self.rows, self.projection = list(rows), projection

    def sort(self, fields, direction=None):
        fields = [(fields, direction)] if isinstance(fields, str) else fields
        for key, order in reversed(fields):
            self.rows.sort(key=lambda row: (value(row, key) is not None, value(row, key)), reverse=order == -1)
        return self

    def skip(self, count):
        self.rows = self.rows[count:]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __iter__(self):
        return (project(row, self.projection) for row in self.rows)


class Collection:
    def __init__(self, db):
        self.db, self.rows, self.indexes = db, [], []

    def create_index(self, keys, **options):
        if options.get('unique'):
            fields = tuple(key for key, _ in keys)
            if fields not in self.indexes:
                self.indexes.append(fields)

    def _unique(self, candidate):
        for fields in [('_id',), *self.indexes]:
            if any(all(value(row, field) == value(candidate, field) for field in fields) for row in self.rows):
                raise DuplicateKeyError('synthetic duplicate')

    def find(self, query, projection=None, session=None):
        with self.db.lock:
            return Cursor([row for row in self.rows if matches(row, query)], projection)

    def find_one(self, query, projection=None, sort=None, session=None):
        cursor = self.find(query, projection, session)
        if sort:
            cursor.sort(sort)
        return next(iter(cursor), None)

    def count_documents(self, query, session=None):
        with self.db.lock:
            return sum(matches(row, query) for row in self.rows)

    def insert_one(self, document, session=None):
        with self.db.lock:
            candidate = deepcopy(document)
            candidate.setdefault('_id', str(self.db.sequence))
            self.db.sequence += 1
            self._unique(candidate)
            self.rows.append(candidate)
            return SimpleNamespace(inserted_id=candidate['_id'])

    def _apply(self, row, update, inserted=False):
        for key, val in update.get('$set', {}).items():
            set_value(row, key, val)
        if inserted:
            for key, val in update.get('$setOnInsert', {}).items():
                set_value(row, key, val)
        for key, increment in update.get('$inc', {}).items():
            set_value(row, key, (value(row, key) or 0) + increment)

    def update_one(self, query, update, upsert=False, session=None):
        with self.db.lock:
            for row in self.rows:
                if matches(row, query):
                    self._apply(row, update)
                    return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
            if upsert:
                candidate = deepcopy(query)
                self._apply(candidate, update, True)
                result = self.insert_one(candidate, session)
                return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=result.inserted_id)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def update_many(self, query, update, session=None):
        with self.db.lock:
            for row in self.rows:
                if matches(row, query):
                    self._apply(row, update)

    def find_one_and_update(self, query, update, sort=None, return_document=None, session=None):
        with self.db.lock:
            row = self.find_one(query, sort=sort, session=session)
            if row is None:
                return None
            self.update_one({'_id': row['_id']}, update, session=session)
            return self.find_one({'_id': row['_id']}, session=session)


class Session:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def with_transaction(self, callback, **options):
        with self.db.lock:
            self.db.transaction_options = options
            snapshot = {key: deepcopy(collection.rows) for key, collection in self.db.collections.items()}
            try:
                result = callback(self)
                if self.db.fail_commit:
                    self.db.fail_commit = False
                    raise RuntimeError('synthetic transaction failure')
                return result
            except BaseException:
                for key, collection in self.db.collections.items():
                    collection.rows = snapshot.get(key, [])
                raise


class Database:
    def __init__(self):
        self.lock = threading.RLock()
        self.collections = {}
        self.sequence = 0
        self.fail_commit = False
        self.closed = 0
        self.client = self

    def __getitem__(self, name):
        if not name.startswith('research_'):
            raise AssertionError('Legacy collections must not be accessed')
        return self.collections.setdefault(name, Collection(self))

    def start_session(self):
        return Session(self)

    def close(self):
        self.closed += 1


class Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds=10):
        self.now += timedelta(seconds=seconds)
