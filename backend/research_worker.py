"""One local worker; source I/O stays outside transactions and HTTP requests."""
import logging
import time

from .research_repository import LeaseLost
from .research_sources import SourceFailure, connector_for, validate_page
from .research_diagnostics import configure_logging, event, CONTEXT


class ResearchWorker:
    def __init__(self, repository, connector=None, after_stage=None):
        self.repository = repository
        self.connector = connector
        self.after_stage = after_stage  # Fault-injection seam: never configured by HTTP.

    def tick(self):
        try:
            study = self.repository.claim_study()
        except Exception as error:
            event('worker_claim_failed', level=logging.ERROR, error=error)
            raise
        if study is None:
            return False
        log_token = CONTEXT.set({'study_id': study['_id'], 'source': study['source']})
        started = time.perf_counter()
        try:
            task = self.repository.claim_task(study)
            if task is None:
                return True
            CONTEXT.set({'study_id': study['_id'], 'task_id': task['_id'], 'source': study['source']})
            event('worker_batch_started', study_id=study['_id'], task_id=task['_id'], source=study['source'], kind=task['kind'])
            try:
                if task['pending'] is None:
                    connector = self.connector or connector_for(study['source'])
                    limit = study['limits']['batch_size']
                    if study['source'] == 'tiktok' and task['kind'] == 'acquire':
                        limit = min(limit, study['target_records'] - study['counters']['prepared'])
                    page = connector.read(topic=study['topic'], config=study['source_config'],
                        kind=task['kind'], publication_id=task['publication_id'], cursor=task['cursor'],
                        limit=limit, attempt=task['attempts'])
                    validate_page(page, task, limit, study['source'])
                    counts = self.repository.stage_page(study, task, page)
                    event('worker_batch_staged', kind=task['kind'], committed_counts=counts)
                    if self.after_stage:
                        self.after_stage()
                self.repository.confirm_page(study, task)
                event('worker_batch_confirmed', kind=task['kind'], recovered_pending=task['pending'] is not None)
            except LeaseLost:
                pass
            except SourceFailure as error:
                event('worker_source_failed', level=logging.ERROR, study_id=study['_id'], task_id=task['_id'], source=study['source'], code=error.code if error.code in ('source_structure_changed', 'source_load_timeout', 'access_restricted', 'browser_unavailable', 'source_permission_missing', 'checkpoint_changed') else 'source_failure', error=error)
                code = error.code if error.code in ('synthetic_failure', 'invalid_provenance', 'source_unavailable', 'credentials_missing', 'quota_exceeded', 'comments_disabled', 'provider_transient', 'provider_access_denied', 'invalid_source_response', 'source_permission_missing', 'access_restricted', 'checkpoint_changed', 'source_structure_changed', 'source_load_timeout', 'session_busy', 'browser_unavailable') else 'source_unavailable'
                self.repository.fail_task(study, task, code, error.retryable)
            except Exception as error:
                event('worker_processing_failed', level=logging.ERROR, study_id=study['_id'], task_id=task['_id'], source=study['source'], error=error)
                # Traceback frames remain local; no exception message or payload is exposed.
                self.repository.fail_task(study, task, 'processing_failed')
            event('worker_batch_finished', study_id=study['_id'], task_id=task['_id'], source=study['source'], elapsed_seconds=round(time.perf_counter()-started, 4))
        except LeaseLost:
            pass
        except Exception as error:
            event('worker_batch_failed', level=logging.ERROR, error=error)
            raise
        finally:
            try:
                self.repository.release(study, time.perf_counter() - started)
            except Exception as error:
                event('worker_release_failed', level=logging.ERROR, error=error)
                raise
            finally:
                CONTEXT.reset(log_token)
        return True


def run_worker(*, once=False, poll_seconds=1):
    configure_logging()
    from .database import get_database
    from .research_repository import ResearchRepository
    database = get_database()
    try:
        repository = ResearchRepository(database)
        repository.ensure_indexes()
        worker = ResearchWorker(repository)
        while True:
            worked = worker.tick()
            if once:
                return
            if not worked:
                time.sleep(poll_seconds)
    finally:
        database.client.close()
