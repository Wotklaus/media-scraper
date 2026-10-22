"""Independent API: GET is read-only; only POST can call OpenAI."""

from fastapi import APIRouter, Depends, HTTPException, Query

from .database import get_database
from .embedding_repository import EmbeddingRepository
from .embeddings import EmbeddingService

router = APIRouter(prefix='/api/embeddings', tags=['embeddings'])


def embedding_service():
    database = None
    try:
        database = get_database()
        yield EmbeddingService(EmbeddingRepository(database))
    except LookupError:
        raise HTTPException(404, 'No se encontró el perfil, la publicación o su embedding actual.') from None
    except ValueError:
        raise HTTPException(400, 'Los datos de la solicitud o los vectores no son válidos.') from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'No se pudo acceder al servicio de embeddings.') from None
    finally:
        if database is not None:
            try:
                database.client.close()
            except Exception:
                pass


@router.post('/{username}')
def generate_embeddings(username: str, limit: int = Query(10, ge=1, le=10),
                        service: EmbeddingService = Depends(embedding_service)):
    return service.generate(username, limit)


@router.get('/{username}')
def list_embeddings(username: str, limit: int = Query(10, ge=1, le=10),
                    service: EmbeddingService = Depends(embedding_service)):
    return service.list(username, limit)


@router.get('/{username}/similarity')
def publication_similarity(username: str, first_id: str, second_id: str,
                           service: EmbeddingService = Depends(embedding_service)):
    return service.similarity(username, first_id, second_id)
