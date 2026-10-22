"""Read-only semantic dashboard plus one explicit, bounded interpretation POST."""

from datetime import datetime
from hashlib import sha256
from itertools import combinations
import math
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from .database import get_database
from .embedding_repository import EmbeddingRepository
from .embeddings import MODEL, DIMENSIONS, cosine_similarity
from .semantic_projection import pca_2d
from .semantic_analysis import SemanticAnalysis, AnalysisBusy, AnalysisFailure, ANALYSIS_MODEL
from .analysis_errors import diagnostic
from .ocean_analysis import OceanAnalysis

router = APIRouter(prefix='/api/semantics', tags=['semantics'])
TRAITS = ('openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism')


def publication_link(value):
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme == 'https' and parts.netloc == 'www.tiktok.com' and '/video/' in parts.path:
            return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    except ValueError:
        pass
    return None


class SemanticWorkspace:
    def __init__(self, database):
        self.database = database
        self.repository = EmbeddingRepository(database)

    def source(self, username):
        username = self.repository.profile(username)
        return username, self.repository.publications(username, 10)

    def valid_texts(self, username):
        username, publications = self.source(username)
        return username, [row for row in publications
                          if isinstance(row.get('description'), str) and row['description'].strip()]

    def map(self, username):
        username, publications = self.source(username)
        rows, vectors = [], []
        for row in publications:
            text = row.get('description')
            if not isinstance(text, str) or not text.strip():
                continue
            document = self.repository.find({'publication_id': row['publication_id'],
                'profile_username': username, 'model': MODEL,
                'content_hash': sha256(text.strip().encode()).hexdigest()})
            if document is None:
                continue
            try:
                vector = document['vector']
                if len(vector) != DIMENSIONS:
                    continue
                cosine_similarity(vector, vector)
            except (TypeError, ValueError, KeyError):
                continue
            rows.append({'publication_id': row['publication_id'],
                         'description': text.strip()[:117] + ('…' if len(text.strip()) > 117 else ''),
                         'url': publication_link(row.get('url'))})
            vectors.append(vector)
        projection = pca_2d(vectors)
        points = [{**row, 'x': xy[0], 'y': xy[1]} for row, xy in zip(rows, projection['coordinates'])]
        related = sorted(({'first': rows[i], 'second': rows[j],
                           'similarity': cosine_similarity(vectors[i], vectors[j])}
                          for i, j in combinations(range(len(rows)), 2)),
                         key=lambda pair: pair['similarity'], reverse=True)[:5]
        return {'profile_id': username.casefold(), 'username': username, 'model': MODEL,
                'method': 'centered_pca', 'limit': 10, 'points': points, 'related': related,
                'explained_variance_ratio': projection['explained_variance_ratio'], 'rank': projection['rank']}

    def analysis(self, username, generate=False):
        username, texts = self.valid_texts(username)
        service = SemanticAnalysis(self.database)
        return service.generate(username, texts) if generate else service.latest(username, texts)

    def ocean(self, username, generate=False, regenerate=False):
        username, texts = self.valid_texts(username)
        service = OceanAnalysis(self.database)
        return service.generate(username, texts, regenerate=regenerate) if generate else service.latest(username, texts)

    def evaluation(self, username):
        username = self.repository.profile(username)
        empty = {'profile_id': username.casefold(), 'status': 'unavailable', 'evaluation': None}
        # Future importer contract only: never derive this collection from TikTok/OpenAI.
        document = self.database['big_five_evaluations'].find_one(
            {'profile_username': username, 'source': 'validated_questionnaire', 'status': 'validated'},
            sort=[('completed_at', -1)])
        if not document:
            return empty
        instrument = document.get('instrument', {})
        scores = document.get('scores', {})
        if (not isinstance(instrument, dict) or instrument.get('name') not in ('BFI-2', 'NEO-PI-R', 'IPIP-NEO-120')
                or not isinstance(instrument.get('version'), str) or not instrument['version'].strip()
                or not isinstance(document.get('scoring_version'), str) or not document['scoring_version'].strip()
                or not isinstance(document.get('completed_at'), datetime)
                or document.get('scale') != {'min': 0, 'max': 100}
                or not isinstance(scores, dict) or set(scores) != set(TRAITS)):
            return empty
        if any(isinstance(score, bool) or not isinstance(score, (int, float))
               or not math.isfinite(score) or not 0 <= score <= 100 for score in scores.values()):
            return empty
        return {'profile_id': username.casefold(), 'status': 'available', 'evaluation': {
            'instrument': {'name': instrument['name'], 'version': instrument['version']},
            'completed_at': document['completed_at'], 'scale': {'min': 0, 'max': 100},
            'scores': scores}}


def semantic_workspace():
    database = None
    try:
        database = get_database()
        yield SemanticWorkspace(database)
    except HTTPException:
        raise
    except LookupError:
        raise HTTPException(404, 'El perfil no está almacenado en MongoDB.') from None
    except AnalysisBusy as error:
        raise HTTPException(409, str(error)) from None
    except AnalysisFailure as error:
        raise HTTPException(error.status_code, error.public()) from None
    except ValueError:
        raise HTTPException(422, 'No hay textos válidos o superan el límite de análisis.') from None
    except Exception as error:
        failure = diagnostic(error, 'storage', ANALYSIS_MODEL)
        raise HTTPException(failure.status_code, failure.public()) from None
    finally:
        if database is not None:
            try:
                database.client.close()
            except Exception:
                pass


@router.get('/{username}/map')
def semantic_map(username: str, service: SemanticWorkspace = Depends(semantic_workspace)):
    return service.map(username)


@router.get('/{username}/analysis')
def stored_analysis(username: str, service: SemanticWorkspace = Depends(semantic_workspace)):
    return service.analysis(username)


@router.post('/{username}/analysis')
def generate_analysis(username: str, service: SemanticWorkspace = Depends(semantic_workspace)):
    return service.analysis(username, generate=True)


@router.get('/{username}/big-five')
def big_five_evaluation(username: str, service: SemanticWorkspace = Depends(semantic_workspace)):
    return service.evaluation(username)


class OceanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    regenerate: bool = False
    confirm_cost: bool = False


@router.get('/{username}/ocean')
def stored_ocean(username: str, service: SemanticWorkspace = Depends(semantic_workspace)):
    return service.ocean(username)


@router.post('/{username}/ocean')
def generate_ocean(username: str, request: OceanRequest | None = None,
                   service: SemanticWorkspace = Depends(semantic_workspace)):
    options = request or OceanRequest()
    if options.regenerate and not options.confirm_cost:
        raise HTTPException(422, 'Para regenerar debes confirmar explícitamente el costo.')
    return service.ocean(username, generate=True, regenerate=options.regenerate)
