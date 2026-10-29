"""One local worker; source I/O stays outside transactions and HTTP requests."""
import logging
import time

from .research_repository import LeaseLost
from .research_sources import SourceFailure, connector_for, validate_page

logger = logging.getLogger(__name__)


class ResearchWorker:
    def __init__(self, repository, connector=None, after_stage=None):
        self.repository = repository
        self.connector = connector
        self.after_stage = after_stage  # Fault-injection seam: never configured by HTTP.

    def tick(self):
        study = self.repository.claim_study()
        if study is None:
            return False
        started = time.perf_counter()
        try:
            task = self.repository.claim_task(study)
            if task is None:
                return True
            try:
                if task['pending'] is None:
                    connector = self.connector or connector_for(study['source'])
                    page = connector.read(topic=study['topic'], config=study['source_config'],
                        kind=task['kind'], publication_id=task['publication_id'], cursor=task['cursor'],
                        limit=study['limits']['batch_size'], attempt=task['attempts'])
                    validate_page(page, task, study['limits']['batch_size'], study['source'])
                    self.repository.stage_page(study, task, page)
                    if self.after_stage:
                        self.after_stage()
                self.repository.confirm_page(study, task)
            except LeaseLost:
                pass
            except SourceFailure as error:
                code = error.code if error.code in ('synthetic_failure', 'invalid_provenance', 'source_unavailable') else 'source_unavailable'
                self.repository.fail_task(study, task, code, error.retryable)
            except Exception:
                # No raw exception, source body, topic or credential enters logs/errors.
                self.repository.fail_task(study, task, 'processing_failed')
            logger.info('research_batch study_id=%s task_id=%s synthetic=true', study['_id'], task['_id'])
        except LeaseLost:
            pass
        finally:
            self.repository.release(study, time.perf_counter() - started)
        return True


def run_worker(*, once=False, poll_seconds=1):
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
