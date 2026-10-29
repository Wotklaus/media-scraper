"""Controlled in-memory benchmark. Run once per process; never connects to MongoDB."""
import json
from pathlib import Path
import resource
import sys
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.research_models import StudyCreate, TERMINAL
from backend.research_repository import ResearchRepository
from backend.research_worker import ResearchWorker
from research_fake import Clock, Database


def benchmark(target):
    tracemalloc.start()
    started = time.perf_counter()
    db, clock = Database(), Clock()
    repo = ResearchRepository(db, clock)
    study = repo.create(StudyCreate(topic='Investigación sintética de texto libre', target_records=target))
    identity = study['study_id']
    repo.control(identity, 'start')
    worker = ResearchWorker(repo)
    for _ in range(10000):
        if repo.raw_study(identity)['status'] in TERMINAL:
            break
        worker.tick()
        clock.advance(1)
    result = repo.detail(identity)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result['status'] == 'target_reached'
    assert result['counters']['prepared'] == target
    assert repo.records.count_documents({'study_id': identity}) == target
    return {'target': target, 'prepared': result['counters']['prepared'], 'seconds': round(elapsed, 4),
        'python_peak_mib': round(peak / 1024**2, 3),
        'process_peak_rss_mib_linux': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 3),
        'batches': result['counters']['batches'], 'environment': 'transactional in-memory double, synthetic connector, tracemalloc enabled; NOT Atlas/TikTok'}


if __name__ == '__main__':
    print(json.dumps(benchmark(int(sys.argv[1]) if len(sys.argv) > 1 else 1000), ensure_ascii=False))
