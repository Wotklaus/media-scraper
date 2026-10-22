"""Read stored publications and persist embeddings without touching extraction data."""

from pymongo.errors import DuplicateKeyError


MAX_PUBLICATIONS = 10


def validate_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PUBLICATIONS:
        raise ValueError('El límite debe estar entre 1 y 10.')


class EmbeddingRepository:
    def __init__(self, database):
        self.database = database

    def profile(self, username):
        key = username.strip().lstrip('@').casefold()
        if not key:
            raise ValueError('El username no puede estar vacío.')
        profile = self.database['profiles'].find_one(
            {'username_key': key}, {'_id': 0, 'username': 1})
        if profile is None:
            raise LookupError('El perfil no está almacenado en MongoDB.')
        return profile['username']

    def publications(self, username, limit=MAX_PUBLICATIONS):
        validate_limit(limit)
        return list(self.database['publications'].find(
            {'profile_username': username},
            {'_id': 0, 'publication_id': 1, 'profile_username': 1, 'description': 1, 'url': 1},
        ).sort('publication_id', -1).limit(limit))

    def ensure_indexes(self):
        self.database['embeddings'].create_index(
            [('publication_id', 1), ('model', 1), ('content_hash', 1)],
            unique=True, name='publication_model_content_unique')
        self.database['embeddings'].create_index([('profile_username', 1), ('generated_at', -1)])

    def find(self, identity):
        return self.database['embeddings'].find_one(identity, {'_id': 0})

    def save(self, identity, document):
        try:
            result = self.database['embeddings'].update_one(
                identity, {'$setOnInsert': document}, upsert=True)
            return result.upserted_id is not None
        except DuplicateKeyError:
            # Another request may have inserted the same content concurrently.
            if self.find(identity) is None:
                raise
            return False

    def list(self, username, limit=MAX_PUBLICATIONS):
        validate_limit(limit)
        return list(self.database['embeddings'].find(
            {'profile_username': username}, {'_id': 0},
        ).sort([('generated_at', -1), ('publication_id', -1)]).limit(limit))
