"""Explicit, bounded embedding generation. Importing this module performs no I/O."""

from datetime import datetime, timezone
from hashlib import sha256
import math

from openai import OpenAI

from .database import ENV_FILE
from .embedding_repository import MAX_PUBLICATIONS, validate_limit

MODEL = 'text-embedding-3-small'
DIMENSIONS = 1536


def create_openai_client():
    # Read only the local configuration; never print secrets or SDK exceptions.
    config = {}
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            key, separator, value = line.partition('=')
            if separator:
                config[key.strip()] = value.strip().strip('"').strip("'")
    key = config.get('OPENAI_API_KEY')
    if not key:
        raise RuntimeError('OPENAI_API_KEY no está configurada en backend/.env.')
    return OpenAI(api_key=key, max_retries=0, timeout=30.0)


def cosine_similarity(first, second):
    """Cosine in [-1, 1]; undefined/invalid vectors raise ValueError."""
    if not first or len(first) != len(second):
        raise ValueError('Los vectores deben tener la misma dimensión y no estar vacíos.')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for vector in (first, second) for v in vector):
        raise ValueError('Los vectores deben contener números finitos.')
    norm_first, norm_second = math.hypot(*first), math.hypot(*second)
    if not norm_first or not norm_second or not math.isfinite(norm_first + norm_second):
        raise ValueError('Los vectores deben tener normas finitas distintas de cero.')
    score = math.fsum((a / norm_first) * (b / norm_second) for a, b in zip(first, second))
    return max(-1.0, min(1.0, score))


class EmbeddingService:
    def __init__(self, repository, client_factory=create_openai_client):
        self.repository = repository
        self.client_factory = client_factory

    def generate(self, username, limit=MAX_PUBLICATIONS):
        validate_limit(limit)
        username = self.repository.profile(username)
        publications = self.repository.publications(username, limit)
        self.repository.ensure_indexes()  # Only explicit generation creates indexes.
        result = dict(username=username, model=MODEL, processed=len(publications),
                      generated=0, reused=0, failed=0, skipped=0, results=[])
        client = None
        try:
            for publication in publications:
                publication_id = publication.get('publication_id')
                item = {'publication_id': publication_id}
                text = publication.get('description')
                if not isinstance(text, str) or not text.strip():
                    result['skipped'] += 1
                    result['results'].append({**item, 'status': 'skipped', 'error': 'empty_description'})
                    continue
                text = text.strip()
                identity = dict(publication_id=publication_id, model=MODEL,
                                content_hash=sha256(text.encode('utf-8')).hexdigest())
                try:
                    if not isinstance(publication_id, str) or not publication_id:
                        raise ValueError('Invalid publication ID')
                    if self.repository.find(identity) is not None:
                        status = 'reused'
                    else:
                        if client is None:
                            client = self.client_factory()
                        response = client.embeddings.create(
                            model=MODEL, input=text, dimensions=DIMENSIONS, encoding_format='float')
                        vector = response.data[0].embedding
                        if len(vector) != DIMENSIONS:
                            raise ValueError('Invalid embedding dimensions')
                        cosine_similarity(vector, vector)  # Also validates finite, nonzero values.
                        document = {**identity, 'profile_username': username, 'text': text,
                                    'vector': vector, 'generated_at': datetime.now(timezone.utc)}
                        status = 'generated' if self.repository.save(identity, document) else 'reused'
                    result[status] += 1
                    result['results'].append({**item, 'status': status})
                except Exception:
                    result['failed'] += 1
                    result['results'].append({**item, 'status': 'failed', 'error': 'embedding_failed'})
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
        return result

    def list(self, username, limit=MAX_PUBLICATIONS):
        validate_limit(limit)
        username = self.repository.profile(username)
        documents = self.repository.list(username, limit)
        return {'username': username, 'count': len(documents), 'embeddings': documents}

    def similarity(self, username, first_id, second_id):
        """Compare current stored descriptions, never generate missing vectors."""
        username = self.repository.profile(username)
        vectors = []
        for publication_id in (first_id, second_id):
            publication = self.repository.database['publications'].find_one(
                {'publication_id': publication_id, 'profile_username': username},
                {'_id': 0, 'description': 1})
            text = publication.get('description') if publication else None
            if not isinstance(text, str) or not text.strip():
                raise LookupError('La publicación no tiene una descripción disponible.')
            document = self.repository.find(dict(publication_id=publication_id, model=MODEL,
                content_hash=sha256(text.strip().encode('utf-8')).hexdigest()))
            if document is None:
                raise LookupError('No existe un embedding para la descripción actual.')
            vectors.append(document['vector'])
        return {'username': username, 'first_publication_id': first_id,
                'second_publication_id': second_id, 'model': MODEL,
                'similarity': cosine_similarity(*vectors)}
