"""Read-only Benford endpoint with an explicit OpenAPI response contract."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from .database import get_database
from .benford_repository import BenfordRepository

Metric = Literal['views', 'likes', 'comments_count', 'shares', 'saves']
Dataset = Literal['latest', 'history']
router = APIRouter(prefix='/api/benford', tags=['Benford'])


class DigitDistribution(BaseModel):
    digit: int
    observed_count: int
    expected_count: float
    observed_probability: float | None
    theoretical_probability: float
    observed_percent: float | None
    theoretical_percent: float
    difference_percentage_points: float | None


class Exclusions(BaseModel):
    missing: int
    zero: int
    negative: int
    invalid: int


class BenfordResponse(BaseModel):
    username: str
    metric: Metric
    metric_label: str
    dataset: Dataset
    source_available: bool
    run_id: str | None
    extracted_at: datetime | None
    selection_policy: str
    duplicates_removed: int
    invalid_publication_records: int
    status: Literal['empty', 'exploratory']
    total_records: int
    valid_records: int
    excluded_records: int
    exclusions: Exclusions
    distribution: list[DigitDistribution]
    mad: float | None
    chi_squared: float | None
    degrees_of_freedom: int
    expected_counts_sufficient: bool
    low_expected_digits: list[int]
    p_value: None
    inference_performed: bool
    orders_spanned: int | None
    warnings: list[str]
    interpretation: str
    disclaimer: str


def benford_repository(
    username: Annotated[str, Path(pattern=r'^@?[A-Za-z0-9._]{1,24}$')],
    metric: Metric = 'views', dataset: Dataset = 'latest',
):
    # Validate before opening MongoDB, including when its configuration is absent.
    database = None
    try:
        database = get_database()
        yield BenfordRepository(database)
    except HTTPException:
        raise
    except LookupError:
        raise HTTPException(404, 'El perfil no está almacenado en MongoDB.') from None
    except Exception:
        raise HTTPException(503, 'No se pudieron consultar los datos para Benford.') from None
    finally:
        if database is not None:
            try:
                database.client.close()
            except Exception:
                pass


@router.get('/{username}', response_model=BenfordResponse)
def analyze_benford(
    username: Annotated[str, Path(pattern=r'^@?[A-Za-z0-9._]{1,24}$')],
    metric: Metric = 'views', dataset: Dataset = 'latest',
    repository: BenfordRepository = Depends(benford_repository),
):
    return repository.analyze(username, metric, dataset)
