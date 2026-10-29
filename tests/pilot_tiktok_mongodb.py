"""Explicitly authorized small REAL pilot, exclusively in a new isolated MongoDB.

Never auto-discovered as a test. Two publications, five comments per publication,
ten prepared comments maximum. Requires operator authorization and local replica set.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integration_research_mongodb import Context
from backend.research_diagnostics import configure_logging
from backend.research_models import StudyCreate, ACTIVE
from backend.research_repository import ResearchRepository
from backend.research_tiktok import TikTokConnector
from backend.research_worker import ResearchWorker


def run(context, topic):
    repo = ResearchRepository(context.db)
    context.db['_integration_manifest'].update_one({'_id': 'isolation'}, {'$set': {
        'purpose': 'authorized-limited-tiktok-pilot', 'synthetic': False,
        'max_publications': 2, 'max_comments_per_publication': 5, 'target_records': 10}})
    study = repo.create(StudyCreate(topic=topic, source='tiktok', target_records=10,
        limits={'batch_size': 5, 'time_budget_seconds': 120},
        source_config={'max_publications': 2, 'max_comments_per_publication': 5, 'max_scrolls': 1}))
    identity = study['study_id']
    repo.control(identity, 'start')
    worker = ResearchWorker(repo, TikTokConnector())
    deadline, ticks = time.monotonic() + 120, 0
    previous_permission = os.environ.get('MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED')
    # Only main's required --authorized-external permits this scoped acquisition.
    os.environ['MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED'] = '1'
    try:
        while repo.detail(identity)['status'] in ACTIVE and time.monotonic() < deadline and ticks < 8:
            if worker.tick():
                ticks += 1
                detail = repo.detail(identity)
                print(json.dumps({'event': 'pilot_progress', 'study_id': identity,
                    'status': detail['status'], 'counters': detail['counters'],
                    'last_error': detail['last_error']}), flush=True)
            else:
                time.sleep(0.5)
    finally:
        if previous_permission is None:
            os.environ.pop('MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED', None)
        else:
            os.environ['MEDIA_SCRAPER_TIKTOK_THEME_ALLOWED'] = previous_permission
        if repo.detail(identity)['status'] in ACTIVE:
            repo.control(identity, 'pause')
    # Independent client proves stored records, not the extractor's in-memory list.
    with context.new_client() as client:
        stored = client[context.name].research_records.count_documents({'study_id': identity})
    detail = repo.detail(identity)
    if stored != detail['counters']['prepared']:
        raise RuntimeError('Pilot stored records and prepared counter disagree')
    return {'real_external_acquisition': True, 'database': context.name, 'study_id': identity,
        'status': detail['status'], 'confirmed_records': stored, 'counters': detail['counters'],
        'last_error': detail['last_error'], 'ticks': ticks,
        'target_verified': detail['status'] == 'target_reached' and stored == 10}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uri', required=True, help='Disposable local msIntegration replica set; never backend/.env')
    parser.add_argument('--database', default='media_scraper_integration_pilot_' + uuid4().hex[:12])
    parser.add_argument('--topic', required=True)
    parser.add_argument('--browser', choices=('headless', 'visible'), default='headless',
                        help='Use the same visible browser as the diagnostic, or headless; no automatic fallback')
    parser.add_argument('--confirm-isolated', required=True, action='store_true')
    parser.add_argument('--authorized-external', required=True, action='store_true',
                        help='Explicit permission to navigate real TikTok using the local session')
    args = parser.parse_args()
    os.environ['MEDIA_SCRAPER_TIKTOK_HEADLESS'] = '0' if args.browser == 'visible' else '1'
    context = Context(args.uri, args.database, 'msIntegration')
    try:
        configure_logging()
        print(json.dumps(run(context, args.topic)), flush=True)
        return 0
    finally:
        context.client.close()


if __name__ == '__main__':
    raise SystemExit(main())
