"""Read-only workspace over stored profiles, publications and current embeddings."""

from hashlib import sha256
from itertools import combinations

from fastapi import APIRouter, Depends, HTTPException

from .database import get_database
from .embedding_repository import EmbeddingRepository, MAX_PUBLICATIONS
from .embeddings import MODEL, DIMENSIONS, cosine_similarity

router = APIRouter(prefix='/api/stored-profiles', tags=['stored profiles'])


class StoredProfiles:
    def __init__(self, database):
        self.database = database

    def profiles(self):
        profiles = list(self.database['profiles'].find(
            {}, {'_id': 0, 'username': 1, 'nickname': 1, 'username_key': 1}
        ).sort('username_key', 1))
        return {'profiles': profiles, 'count': len(profiles)}

    def publications(self, username):
        username = EmbeddingRepository(self.database).profile(username)
        publications = list(self.database['publications'].find(
            {'profile_username': username},
            {'_id': 0, 'publication_id': 1, 'profile_username': 1, 'description': 1, 'url': 1}
        ).sort('publication_id', -1))
        stored = self.database['embeddings'].find(
            {'profile_username': username, 'model': MODEL},
            {'_id': 0, 'publication_id': 1, 'content_hash': 1, 'vector': 1, 'generated_at': 1})
        by_identity = {(doc['publication_id'], doc['content_hash']): doc for doc in stored}
        vectors, rows = {}, []
        for publication in publications:
            text = publication.get('description')
            text = text.strip() if isinstance(text, str) else ''
            content_hash = sha256(text.encode('utf-8')).hexdigest() if text else None
            document = by_identity.get((publication['publication_id'], content_hash))
            valid = False
            if document is not None:
                try:
                    vector = document['vector']
                    if len(vector) == DIMENSIONS:
                        cosine_similarity(vector, vector)
                        valid = True
                except (ValueError, TypeError, KeyError):
                    pass
            if valid:
                vectors[publication['publication_id']] = vector
            rows.append({**publication, 'content_hash': content_hash,
                         'embedding_status': 'generated' if valid else 'pending' if text else 'empty',
                         'embedding': {'model': MODEL, 'generated_at': document.get('generated_at')}
                         if valid else None})
        related = sorted(({
            'first_publication_id': first, 'second_publication_id': second,
            'similarity': cosine_similarity(vectors[first], vectors[second]),
        } for first, second in combinations(vectors, 2)), key=lambda pair: pair['similarity'], reverse=True)[:5]
        return {'username': username, 'profile_id': username.casefold(), 'model': MODEL,
                'publications': rows, 'related': related,
                'summary': {'available': len(rows), 'generated': len(vectors),
                            'pending': sum(row['embedding_status'] == 'pending' for row in rows),
                            'empty': sum(row['embedding_status'] == 'empty' for row in rows),
                            'generation_pending': sum(row['embedding_status'] == 'pending'
                                                      for row in rows[:MAX_PUBLICATIONS]),
                            'generation_limit': MAX_PUBLICATIONS}}


def stored_profiles():
    database = None
    try:
        database = get_database()
        yield StoredProfiles(database)
    except LookupError:
        raise HTTPException(404, 'El perfil no está almacenado en MongoDB.') from None
    except ValueError:
        raise HTTPException(400, 'El username no es válido.') from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'No se pudieron consultar los perfiles almacenados.') from None
    finally:
        if database is not None:
            try:
                database.client.close()
            except Exception:
                pass


@router.get('')
def list_profiles(service: StoredProfiles = Depends(stored_profiles)):
    return service.profiles()


@router.get('/{username}/publications')
def list_publications(username: str, service: StoredProfiles = Depends(stored_profiles)):
    return service.publications(username)
