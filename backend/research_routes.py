"""Isolated REST API. Only explicit commands enqueue work; GET never runs a source."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError

from .database import get_database
from .research_models import (StudyCreate, StudyResponse, StudyList, RecordList,
                              TaskList, PublicationList, ResearchCapabilities, maximum_target)
from .research_repository import ResearchRepository, ResearchMissing, ResearchConflict

router = APIRouter(prefix='/api/research', tags=['Investigación Temática'])


def research_repository():
    database = None
    try:
        database = get_database()
        yield ResearchRepository(database)
    except (HTTPException, RequestValidationError):
        raise
    except ResearchMissing:
        raise HTTPException(404, 'La investigación no existe.') from None
    except ResearchConflict as error:
        raise HTTPException(409, str(error)) from None
    except Exception:
        raise HTTPException(503, 'No se pudo acceder al almacenamiento de investigaciones.') from None
    finally:
        if database is not None:
            try:
                database.client.close()
            except Exception:
                pass


@router.get('/sources', response_model=ResearchCapabilities)
def sources():
    return ResearchCapabilities(max_target_records=maximum_target())


@router.post('/studies', response_model=StudyResponse, status_code=201)
def create_study(payload: StudyCreate, repository: ResearchRepository = Depends(research_repository)):
    return repository.create(payload)


@router.get('/studies', response_model=StudyList)
def list_studies(offset: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100),
                 repository: ResearchRepository = Depends(research_repository)):
    return repository.list(offset, limit)


@router.get('/studies/{study_id}', response_model=StudyResponse)
def detail(study_id: UUID, repository: ResearchRepository = Depends(research_repository)):
    return repository.detail(str(study_id))


@router.get('/studies/{study_id}/progress', response_model=StudyResponse)
def progress(study_id: UUID, repository: ResearchRepository = Depends(research_repository)):
    return repository.detail(str(study_id))


@router.post('/studies/{study_id}/start', response_model=StudyResponse, status_code=202)
def start(study_id: UUID, repository: ResearchRepository = Depends(research_repository)):
    return repository.control(str(study_id), 'start')


@router.post('/studies/{study_id}/pause', response_model=StudyResponse)
def pause(study_id: UUID, repository: ResearchRepository = Depends(research_repository)):
    return repository.control(str(study_id), 'pause')


@router.post('/studies/{study_id}/resume', response_model=StudyResponse, status_code=202)
def resume(study_id: UUID, repository: ResearchRepository = Depends(research_repository)):
    return repository.control(str(study_id), 'resume')


@router.post('/studies/{study_id}/cancel', response_model=StudyResponse)
def cancel(study_id: UUID, repository: ResearchRepository = Depends(research_repository)):
    return repository.control(str(study_id), 'cancel')


@router.get('/studies/{study_id}/records', response_model=RecordList)
def records(study_id: UUID, offset: int = Query(0, ge=0, le=1000000), limit: int = Query(50, ge=1, le=100),
            repository: ResearchRepository = Depends(research_repository)):
    return repository.record_page(str(study_id), offset, limit)


@router.get('/studies/{study_id}/tasks', response_model=TaskList)
def tasks(study_id: UUID, offset: int = Query(0, ge=0, le=1000000), limit: int = Query(50, ge=1, le=100),
          repository: ResearchRepository = Depends(research_repository)):
    return repository.task_page(str(study_id), offset, limit)


@router.get('/studies/{study_id}/publications', response_model=PublicationList)
def publications(study_id: UUID, offset: int = Query(0, ge=0, le=1000000), limit: int = Query(50, ge=1, le=100),
                 repository: ResearchRepository = Depends(research_repository)):
    return repository.publication_page(str(study_id), offset, limit)
