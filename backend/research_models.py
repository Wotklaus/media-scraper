"""Contracts for the isolated, synthetic research module."""
from datetime import datetime
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SOURCE_LABEL = 'Datos de prueba — No reales'
ACTIVE = ('queued', 'discovering', 'acquiring')
TERMINAL = ('target_reached', 'partial', 'exhausted', 'failed', 'cancelled')
StudyState = Literal['draft', 'queued', 'discovering', 'acquiring', 'paused',
                     'target_reached', 'partial', 'exhausted', 'failed', 'cancelled']
TaskState = Literal['queued', 'processing', 'retry_wait', 'completed', 'failed', 'cancelled']


def maximum_target():
    return max(1, int(os.getenv('MEDIA_SCRAPER_RESEARCH_MAX_RECORDS', '10000')))


class Limits(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    batch_size: int = Field(50, ge=1, le=100)
    lease_seconds: int = Field(60, ge=10, le=300)
    max_attempts: int = Field(3, ge=1, le=5)
    time_budget_seconds: int = Field(300, ge=1, le=3600)


class SyntheticConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    publications: int = Field(20, ge=1, le=1000)
    comments_per_publication: int = Field(80, ge=1, le=1000)
    failure_mode: Literal['none', 'transient', 'permanent'] = 'none'
    failure_stage: Literal['discover', 'acquire'] = 'acquire'


class StudyCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    topic: str = Field(min_length=1, max_length=500)
    description: str = Field('', max_length=2000)
    source: Literal['synthetic'] = 'synthetic'
    target_records: int = Field(400, ge=1)
    limits: Limits = Field(default_factory=Limits)
    source_config: SyntheticConfig = Field(default_factory=SyntheticConfig)

    @field_validator('topic')
    @classmethod
    def topic_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('El tema no puede estar vacío.')
        return value

    @field_validator('target_records')
    @classmethod
    def target_within_resources(cls, value):
        if value > maximum_target():
            raise ValueError(f'El máximo configurado es {maximum_target()} registros.')
        return value


class Counters(BaseModel):
    prepared: int = 0
    excluded: int = 0
    duplicates: int = 0
    received: int = 0
    publications_discovered: int = 0
    publications_processed: int = 0
    batches: int = 0
    processing_seconds: float = 0


class StudyResponse(BaseModel):
    study_id: str
    topic: str
    description: str
    source: Literal['synthetic']
    synthetic: Literal[True]
    source_label: str
    target_records: int
    status: StudyState
    limits: Limits
    source_config: SyntheticConfig
    counters: Counters
    created_at: datetime
    updated_at: datetime
    last_error: str | None
    stop_reason: str | None
    warnings: list[str]
    pending_tasks: int
    failed_tasks: int
    progress_percent: float


class StudyList(BaseModel):
    studies: list[StudyResponse]
    total: int
    offset: int
    limit: int


class TaskResponse(BaseModel):
    task_id: str
    kind: Literal['discover', 'acquire']
    publication_id: str | None
    status: TaskState
    cursor: str | None
    offset: int
    last_checkpoint: datetime | None
    pending_confirmation: bool
    attempts: int
    failures: int
    last_error: str | None
    updated_at: datetime
    lease_until: datetime


class TaskList(BaseModel):
    tasks: list[TaskResponse]
    total: int
    offset: int
    limit: int


class RecordResponse(BaseModel):
    record_id: str
    publication_id: str
    text: str
    synthetic: Literal[True]
    privacy_version: str
    redactions: int
    created_at: datetime


class RecordList(BaseModel):
    records: list[RecordResponse]
    total: int
    offset: int
    limit: int
    source_label: str = SOURCE_LABEL


class PublicationResponse(BaseModel):
    source: Literal['synthetic']
    publication_id: str
    synthetic: Literal[True]
    description: str
    metrics: dict[str, int]
    discovered_at: datetime
    processed: bool
    source_complete: bool | None = None


class PublicationList(BaseModel):
    publications: list[PublicationResponse]
    total: int
    offset: int
    limit: int


class ResearchCapabilities(BaseModel):
    source: Literal['synthetic'] = 'synthetic'
    source_label: str = SOURCE_LABEL
    synthetic: Literal[True] = True
    max_target_records: int
    max_batch_size: int = 100
