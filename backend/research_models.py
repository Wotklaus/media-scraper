"""Contracts for isolated research acquisition sources."""
from datetime import datetime
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class YouTubeConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    max_publications: int = Field(20, ge=1, le=200)
    max_pages_per_publication: int = Field(20, ge=1, le=200)
    include_replies: bool = False
    published_after: str | None = Field(None, max_length=40)
    published_before: str | None = Field(None, max_length=40)

    @field_validator('published_after', 'published_before')
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('La fecha debe incluir zona horaria.')
            return parsed.isoformat()
        return value

    @model_validator(mode='after')
    def ordered_dates(self):
        if self.published_after and self.published_before and datetime.fromisoformat(self.published_after.replace('Z', '+00:00')) >= datetime.fromisoformat(self.published_before.replace('Z', '+00:00')):
            raise ValueError('El inicio debe ser anterior al final.')
        return self


class TikTokConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    max_publications: int = Field(50, ge=1, le=200)
    max_comments_per_publication: int = Field(200, ge=1, le=2000)
    max_scrolls: int = Field(12, ge=1, le=30)
    batch_timeout_seconds: int = Field(45, ge=10, le=50)


class StudyCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    topic: str = Field(min_length=1, max_length=500)
    description: str = Field('', max_length=2000)
    source: Literal['synthetic', 'youtube', 'tiktok'] = 'synthetic'
    target_records: int = Field(400, ge=1)
    limits: Limits = Field(default_factory=Limits)
    source_config: SyntheticConfig | YouTubeConfig | TikTokConfig = Field(default_factory=SyntheticConfig)

    @model_validator(mode='before')
    @classmethod
    def source_configuration(cls, values):
        if isinstance(values, dict):
            values = dict(values)
            config = {'youtube': YouTubeConfig, 'tiktok': TikTokConfig}.get(values.get('source'), SyntheticConfig)
            values['source_config'] = config.model_validate(values.get('source_config', {}))
        return values

    @model_validator(mode='after')
    def tiktok_lease_budget(self):
        if self.source == 'tiktok' and self.limits.lease_seconds <= self.source_config.batch_timeout_seconds + 5:
            raise ValueError('La reserva debe superar el timeout del navegador en más de cinco segundos.')
        return self

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
    source: Literal['synthetic', 'youtube', 'tiktok']
    synthetic: bool
    source_label: str
    target_records: int
    status: StudyState
    limits: Limits
    source_config: SyntheticConfig | YouTubeConfig | TikTokConfig
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
    synthetic: bool
    source: str = 'synthetic'
    published_at: str | None = None
    record_kind: str = 'comment'
    acquisition_version: str = 'synthetic-v1'
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
    source: Literal['synthetic', 'youtube', 'tiktok']
    publication_id: str
    synthetic: bool
    description: str
    metrics: dict[str, int]
    discovered_at: datetime
    processed: bool
    canonical_url: str | None = None
    platform_id: str | None = None
    author_handle: str | None = None
    title: str = ''
    published_at: str | None = None
    acquisition_version: str = 'synthetic-v1'
    source_complete: bool | None = None


class PublicationList(BaseModel):
    publications: list[PublicationResponse]
    total: int
    offset: int
    limit: int


class SourceCapability(BaseModel):
    source: str
    source_label: str
    synthetic: bool
    available: bool
    discovery: bool = True
    comments: bool = True
    replies: bool = False
    reason: str | None = None


class ResearchCapabilities(BaseModel):
    source: Literal['synthetic'] = 'synthetic'
    source_label: str = SOURCE_LABEL
    synthetic: Literal[True] = True
    max_target_records: int
    max_batch_size: int = 100
    sources: list[SourceCapability] = Field(default_factory=list)
