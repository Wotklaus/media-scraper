"""Controlled mathematical, read-only repository and ASGI endpoint tests."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import math
import unittest
from unittest.mock import Mock, patch

from backend import benford_routes, main
from backend.benford import analyze_values, benford_probabilities, first_significant_digit
from backend.benford_repository import BenfordRepository
from test_embeddings import request


class ReadCursor(list):
    def sort(self, fields):
        for key, direction in reversed(fields):
            super().sort(key=lambda row: str(row.get(key, '')), reverse=direction == -1)
        return self


class ReadCollection:
    def __init__(self, rows):
        self.rows = deepcopy(rows)

    def find(self, query, projection=None):
        return ReadCursor(deepcopy([row for row in self.rows if all(row.get(k) == v for k, v in query.items())]))

    def find_one(self, query, projection=None, sort=None):
        rows = self.find(query, projection)
        if sort:
            rows.sort(sort)
        return rows[0] if rows else None


def publication(identity, value, **fields):
    return dict(publication_id=identity, profile_username='Example', metrics={'views': value}, **fields)


def database():
    collections = {
        'profiles': ReadCollection([{'username': 'Example', 'username_key': 'example'}]),
        'publications': ReadCollection([
            publication('one', 900, last_seen_at='2026-01-01'),
            publication('one', None, last_seen_at='2026-02-01'),
            publication('two', 22, last_seen_at='2026-02-01'),
            dict(publication('foreign', 99), profile_username='Other'),
        ]),
        'extraction_runs': ReadCollection([
            {'profile_username_key': 'example', 'status': 'saved', 'run_id': 'old',
             'extracted_at': datetime(2026, 1, 1, tzinfo=timezone.utc),
             'snapshot': {'publications': [publication('old', 99)]}},
            {'profile_username_key': 'example', 'status': 'saved', 'run_id': 'new',
             'extracted_at': datetime(2026, 2, 1, tzinfo=timezone.utc),
             'snapshot': {'publications': [publication('two', 11)]}},
        ]),
    }
    db = Mock()
    db.__getitem__ = Mock(side_effect=collections.__getitem__)
    return db, collections


class MathematicsTests(unittest.TestCase):
    def test_theoretical_probabilities(self):
        probabilities = benford_probabilities()
        self.assertEqual(len(probabilities), 9)
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], math.log10(2))
        self.assertAlmostEqual(probabilities[8], math.log10(10 / 9))
        self.assertTrue(all(a > b for a, b in zip(probabilities, probabilities[1:])))

    def test_significant_digits_without_log_rounding_or_integer_overflow(self):
        for value, digit in [(1, 1), (999, 9), (1000, 1), (0.0042, 4), (7e-200, 7),
                             (Decimal('0.00000091'), 9), (10**200 + 1, 1), (9.999, 9)]:
            with self.subTest(value=value):
                self.assertEqual(first_significant_digit(value), digit)

    def test_known_counts_mad_and_chi_squared(self):
        result = analyze_values([1, 10, 200, 90])
        counts = [2, 1, 0, 0, 0, 0, 0, 0, 1]
        p = benford_probabilities()
        self.assertEqual([row['observed_count'] for row in result['distribution']], counts)
        self.assertEqual([row['observed_probability'] for row in result['distribution']], [c / 4 for c in counts])
        self.assertAlmostEqual(result['mad'], sum(abs(c / 4 - q) for c, q in zip(counts, p)) / 9)
        self.assertAlmostEqual(result['chi_squared'], sum((c - 4*q)**2 / (4*q) for c, q in zip(counts, p)))
        self.assertAlmostEqual(sum(row['observed_percent'] for row in result['distribution']), 100)
        self.assertEqual(result, analyze_values([90, 200, 10, 1]))

    def test_exclusions_are_separate_and_original_numbers_only(self):
        values = [None, 0, 0.0, -5, 'N/A', '1.2K', '123', True, float('nan'), float('inf'), {}, 12]
        result = analyze_values(values)
        self.assertEqual(result['exclusions'], dict(missing=1, zero=2, negative=1, invalid=7))
        self.assertEqual((result['total_records'], result['valid_records'], result['excluded_records']), (12, 1, 11))
        for value in values[:-1]:
            self.assertIsNone(first_significant_digit(value))

    def test_empty_is_not_a_fictional_zero_distribution(self):
        result = analyze_values([])
        self.assertEqual(result['status'], 'empty')
        self.assertIsNone(result['mad'])
        self.assertIsNone(result['chi_squared'])
        self.assertTrue(all(row['observed_probability'] is None for row in result['distribution']))

    def test_small_sample_and_expected_count_boundary(self):
        small = analyze_values(list(range(1, 11)))
        self.assertFalse(small['expected_counts_sufficient'])
        self.assertTrue(small['low_expected_digits'])
        self.assertTrue(any('Muestra reducida' in warning for warning in small['warnings']))
        self.assertFalse(analyze_values([1] * 109)['expected_counts_sufficient'])
        large = analyze_values([1] * 110)
        self.assertTrue(large['expected_counts_sufficient'])
        self.assertFalse(large['inference_performed'])
        self.assertIsNone(large['p_value'])
        self.assertIn('no demuestra', large['disclaimer'])


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.db, self.collections = database()
        self.service = BenfordRepository(self.db)

    def test_latest_snapshot_is_distinct_from_history_and_newest_run_selected(self):
        latest = self.service.analyze('@EXAMPLE')
        history = self.service.analyze('example', dataset='history')
        self.assertEqual(latest['run_id'], 'new')
        self.assertEqual(latest['valid_records'], 1)
        self.assertEqual(latest['distribution'][0]['observed_count'], 1)
        self.assertEqual(history['distribution'][1]['observed_count'], 1)
        self.assertEqual(history['distribution'][8]['observed_count'], 0)

    def test_history_deduplicates_latest_even_when_metric_missing(self):
        result = self.service.analyze('example', dataset='history')
        self.assertEqual((result['total_records'], result['duplicates_removed']), (2, 1))
        self.assertEqual(result['exclusions']['missing'], 1)

    def test_all_metrics_use_actual_stored_keys_and_do_not_mix(self):
        run = self.collections['extraction_runs'].rows[-1]
        run['snapshot']['publications'][0]['metrics'] = dict(views=11, likes=22, comments_count=33, shares=44, saves=55)
        for metric, digit in zip(('views', 'likes', 'comments_count', 'shares', 'saves'), range(1, 6)):
            result = self.service.analyze('example', metric=metric)
            self.assertEqual(result['valid_records'], 1)
            self.assertEqual(result['distribution'][digit-1]['observed_count'], 1)
        run['snapshot']['publications'][0].pop('metrics')
        self.assertEqual(self.service.analyze('example')['exclusions']['missing'], 1)

    def test_no_latest_snapshot_never_falls_back_to_history(self):
        self.collections['extraction_runs'].rows.clear()
        result = self.service.analyze('example')
        self.assertFalse(result['source_available'])
        self.assertEqual(result['total_records'], 0)
        self.assertEqual(self.service.analyze('example', dataset='history')['total_records'], 2)

    def test_empty_snapshot_duplicates_invalid_ids_and_other_profiles(self):
        run = self.collections['extraction_runs'].rows[-1]
        run['snapshot']['publications'] = [publication('a', 1), publication('a', 2), publication('', 3)]
        result = self.service.analyze('example')
        self.assertEqual((result['duplicates_removed'], result['invalid_publication_records']), (1, 1))
        run['snapshot']['publications'] = []
        result = self.service.analyze('example')
        self.assertTrue(result['source_available'])
        self.assertEqual(result['status'], 'empty')
        with self.assertRaises(LookupError):
            self.service.analyze('missing')

    def test_analysis_does_not_write_or_call_scraper_or_openai(self):
        before = {name: deepcopy(collection.rows) for name, collection in self.collections.items()}
        with patch.object(main, 'scrape_profile', side_effect=AssertionError('No scraping')), patch('backend.embeddings.OpenAI', side_effect=AssertionError('No AI')):
            self.service.analyze('example')
            self.service.analyze('example', dataset='history')
        self.assertEqual(before, {name: collection.rows for name, collection in self.collections.items()})
        self.db.client.assert_not_called()


class EndpointTests(unittest.TestCase):
    def test_response_contract_safe_failures_and_cleanup(self):
        db, _ = database()
        with patch.object(benford_routes, 'get_database', return_value=db):
            status, result = asyncio.run(request('GET', '/api/benford/Example'))
            self.assertEqual(status, 200)
            benford_routes.BenfordResponse.model_validate(result)
            self.assertEqual(result['run_id'], 'new')
            status, result = asyncio.run(request('GET', '/api/benford/Example', b'metric=saves&dataset=history'))
            self.assertEqual((status, result['exclusions']['missing']), (200, 2))
            status, _ = asyncio.run(request('GET', '/api/benford/missing'))
            self.assertEqual(status, 404)
        self.assertEqual(db.client.close.call_count, 3)
        with patch.object(benford_routes, 'get_database', side_effect=RuntimeError('secret-uri')):
            status, result = asyncio.run(request('GET', '/api/benford/Example'))
            self.assertEqual(status, 503)
            self.assertNotIn('secret-uri', str(result))

    def test_invalid_parameters_do_not_open_database(self):
        with patch.object(benford_routes, 'get_database') as connect:
            for path, query in [('/api/benford/bad!', b''), ('/api/benford/' + 'a'*25, b''),
                                ('/api/benford/example', b'metric=followers'), ('/api/benford/example', b'dataset=all')]:
                status, _ = asyncio.run(request('GET', path, query))
                self.assertEqual(status, 422)
            connect.assert_not_called()

    def test_openapi_schema_is_explicit(self):
        schema = main.app.openapi()
        response = schema['paths']['/api/benford/{username}']['get']['responses']['200']
        self.assertTrue(response['content']['application/json']['schema']['$ref'].endswith('BenfordResponse'))
