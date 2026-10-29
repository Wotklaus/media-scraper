"""Required controlled sizes; no remote source, MongoDB or paid API."""
import unittest

from backend.research_models import StudyCreate
from backend.research_repository import ResearchRepository
from backend.research_worker import ResearchWorker
from research_fake import Clock, Database


class ResearchLoadTests(unittest.TestCase):
    def test_200_400_500_and_1000_prepared_unique_records(self):
        for target in (200, 400, 500, 1000):
            with self.subTest(target=target):
                db, clock = Database(), Clock()
                repo = ResearchRepository(db, clock)
                identity = repo.create(StudyCreate(topic='Un tema libre de investigación', target_records=target))['study_id']
                repo.control(identity, 'start')
                worker = ResearchWorker(repo)
                for _ in range(200):
                    worker.tick()
                    clock.advance(1)
                    if repo.raw_study(identity)['status'] == 'target_reached':
                        break
                result = repo.detail(identity)
                self.assertEqual(result['status'], 'target_reached')
                self.assertEqual(result['counters']['prepared'], target)
                self.assertEqual(repo.record_page(identity)['total'], target)
                self.assertEqual(len(repo.record_page(identity, limit=25)['records']), 25)
                self.assertEqual(len({row['record_key'] for row in db['research_records'].rows}), target)
