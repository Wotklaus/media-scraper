"""Lightweight semantic dashboard tests; all data and API responses are synthetic."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import math
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend import main, semantic_routes
from backend.semantic_projection import pca_2d
from backend.structured_analysis import source_schema, literal_fragments
from backend.semantic_analysis import (SemanticAnalysis, Interpretation, ANALYSIS_MODEL,
                                       AnalysisBusy, AnalysisFailure, validate_interpretation)
from test_embeddings import Collection, fixture, request


class AnalysisCollection(Collection):
    def find_one(self, query, projection=None, sort=None):
        rows = list(self.find(query, projection))
        if sort:
            field, direction = sort[0]
            rows.sort(key=lambda row: row.get(field, datetime.min.replace(tzinfo=timezone.utc)), reverse=direction < 0)
        return rows[0] if rows else None

    def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                before = deepcopy(row)
                row.update(deepcopy(update.get('$set', {})))
                return SimpleNamespace(modified_count=int(before != row), upserted_id=None)
        if upsert:
            self.rows.append({**query, **deepcopy(update.get('$setOnInsert', {}))})
            return SimpleNamespace(upserted_id=query['_id'], modified_count=0)
        return SimpleNamespace(upserted_id=None, modified_count=0)


def output():
    finding = {'text': 'Descripción de contenido observable.', 'publication_ids': ['100'],
               'evidence': [{'publication_id': '100', 'quote': 'Descripción 0'}]}
    return {'summary': finding, 'themes': [{'name': 'Contenido descriptivo',
            'publication_ids': ['100'], 'evidence': finding['evidence']}],
            'communication_style': [finding]}


def sdk_response(value, status='completed'):
    return SimpleNamespace(status=status, output_text=json.dumps(value) if value is not None else '',
                           output=[], incomplete_details=SimpleNamespace(reason='max_output_tokens'))


class ProjectionTests(unittest.TestCase):
    def test_two_vectors_preserve_distance_and_have_no_invented_second_axis(self):
        projection = pca_2d([[1, 0], [0, 1]])
        first, second = projection['coordinates']
        self.assertAlmostEqual(math.dist(first, second), math.sqrt(2))
        self.assertAlmostEqual(first[0], -second[0])
        self.assertEqual((first[1], second[1]), (0, 0))
        self.assertEqual(projection['rank'], 1)
        self.assertAlmostEqual(sum(projection['explained_variance_ratio']), 1)

    def test_triangle_preserves_pair_distances_and_is_deterministic(self):
        vectors = [[0, 0, 0], [3, 0, 0], [0, 4, 0]]
        projection = pca_2d(vectors)
        self.assertEqual(projection, pca_2d(vectors))
        self.assertEqual(projection['rank'], 2)
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertAlmostEqual(math.dist(vectors[i], vectors[j]),
                    math.dist(projection['coordinates'][i], projection['coordinates'][j]), places=8)
        self.assertAlmostEqual(sum(point[0] for point in projection['coordinates']), 0)

    def test_degenerate_empty_single_and_identical_points(self):
        self.assertEqual(pca_2d([])['coordinates'], [])
        self.assertEqual(pca_2d([[1, 2]])['coordinates'], [[0, 0]])
        result = pca_2d([[1, 2], [1, 2]])
        self.assertEqual(result['coordinates'], [[0, 0], [0, 0]])
        self.assertEqual(result['rank'], 0)

    def test_three_dimensional_variance_is_not_presented_as_cosine(self):
        result = pca_2d([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]])
        self.assertEqual(result['rank'], 3)
        self.assertAlmostEqual(sum(result['explained_variance_ratio']), 2 / 3)

    def test_invalid_or_unbounded_vectors(self):
        for vectors in ([[1], [1, 2]], [[float('nan')]], [[True]], [[1]] * 11):
            with self.subTest(vectors=vectors), self.assertRaises(ValueError):
                pca_2d(vectors)


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.db, self.embedding_client, _, self.embedding_service = fixture()
        self.db['semantic_analyses'] = AnalysisCollection()
        self.db['big_five_evaluations'] = AnalysisCollection()
        self.workspace = semantic_routes.SemanticWorkspace(self.db)
        self.client = Mock()
        self.client.responses.create.return_value = sdk_response(output())
        self.factory = Mock(return_value=self.client)
        self.analysis = SemanticAnalysis(self.db, self.factory)
        self.username, self.texts = self.workspace.valid_texts('testuser')
        self.block = patch('backend.embeddings.OpenAI', side_effect=AssertionError('Live OpenAI forbidden'))
        self.block.start()

    def tearDown(self):
        self.block.stop()

    def generate(self):
        return self.analysis.generate(self.username, self.texts)

    def test_real_current_vectors_only_and_two_points_only(self):
        self.embedding_service.generate('testuser')
        result = self.workspace.map('testuser')
        self.assertEqual(len(result['points']), 2)
        self.assertEqual(result['rank'], 0)  # Same synthetic vectors are not jittered.
        self.assertEqual(result['points'][0]['x'], result['points'][1]['x'])
        self.assertEqual(result['related'][0]['similarity'], 1)
        self.assertNotIn('vector', result)
        self.db['publications'].rows[0]['description'] = 'Changed'
        self.assertEqual(len(self.workspace.map('testuser')['points']), 1)
        self.db['embeddings'].rows[1]['model'] = 'old-model'
        self.assertEqual(self.workspace.map('testuser')['points'], [])

    def test_invalid_vectors_and_foreign_profiles_are_not_projected(self):
        self.embedding_service.generate('testuser')
        self.db['embeddings'].rows[0]['profile_username'] = 'Other'
        self.db['embeddings'].rows[1]['vector'] = [float('nan')] * 1536
        result = self.workspace.map('testuser')
        self.assertEqual(result['points'], [])
        self.assertEqual(result['related'], [])

    def test_map_limit_related_top_five_cosine_and_original_links(self):
        db, client, _, generator = fixture(15)
        for row in db['publications'].rows:
            row['url'] = f"https://www.tiktok.com/@TestUser/video/{row['publication_id']}?token=private"
            row['description'] += 'x' * 300
        generator.generate('testuser')
        db['embeddings'].rows[0]['vector'] = [-1.0] + [0.0] * 1535
        result = semantic_routes.SemanticWorkspace(db).map('testuser')
        self.assertEqual(len(result['points']), 10)
        self.assertEqual(len(result['related']), 5)
        self.assertTrue(all(pair['similarity'] == 1 for pair in result['related']))
        self.assertTrue(all(len(point['description']) <= 118 for point in result['points']))
        self.assertNotIn('private', str(result))

    def test_analysis_read_is_empty_and_never_calls_openai(self):
        self.assertEqual(self.analysis.latest(self.username, self.texts)['status'], 'empty')
        self.factory.assert_not_called()
        self.assertEqual(self.db['semantic_analyses'].rows, [])

    def test_generation_structured_output_storage_and_minimal_input(self):
        result = self.generate()
        self.assertEqual(result['status'], 'current')
        self.assertFalse(result['reused'])
        call = self.client.responses.create.call_args.kwargs
        self.assertEqual(call['text']['format']['schema'], source_schema(Interpretation, ['p1', 'p2'], {f'p{i+1}': literal_fragments(row['description']) for i, row in enumerate(self.texts)}))
        self.assertTrue(call['text']['format']['strict'])
        self.assertEqual(call['model'], ANALYSIS_MODEL)
        self.assertFalse(call['store'])
        self.assertEqual(call['reasoning'], {'effort': 'none'})
        self.assertNotIn('TestUser', call['input'])
        self.assertNotIn('metrics', call['input'])
        self.assertEqual([row['publication_id'] for row in json.loads(call['input'])], ['p1', 'p2'])
        self.assertNotIn('100', call['input'])
        self.assertEqual(self.db['semantic_analyses'].rows[0]['status'], 'completed')
        self.assertEqual(result['analysis']['generated_at'].tzinfo, timezone.utc)
        self.client.close.assert_called_once()

    def test_reuse_same_content_and_order_independence_without_new_requests(self):
        first = self.generate()
        second = self.analysis.generate(self.username, list(reversed(self.texts)))
        self.assertTrue(second['reused'])
        self.assertEqual(first['analysis'], second['analysis'])
        self.assertEqual(self.client.responses.create.call_count, 1)
        self.assertEqual(len(self.db['semantic_analyses'].rows), 1)

    def test_changed_content_marks_stale_and_get_hides_old_findings(self):
        self.generate()
        self.texts[1]['description'] = 'Changed second text'
        self.assertEqual(self.analysis.latest(self.username, self.texts), {
            'profile_id': 'testuser', 'status': 'stale', 'analysis': None})
        self.assertFalse(self.generate()['reused'])
        self.assertEqual(len(self.db['semantic_analyses'].rows), 2)

    def test_profiles_are_isolated_even_with_identical_texts(self):
        self.generate()
        self.assertEqual(self.analysis.latest('other', self.texts)['status'], 'empty')
        self.assertFalse(self.analysis.generate('other', self.texts)['reused'])
        self.assertEqual(len(self.db['semantic_analyses'].rows), 2)

    def test_concurrent_request_is_reserved_before_provider_call(self):
        def respond(**kwargs):
            with self.assertRaises(AnalysisBusy):
                self.generate()
            return sdk_response(output())
        self.client.responses.create.side_effect = respond
        self.generate()
        self.assertEqual(self.client.responses.create.call_count, 1)

    def test_refusal_incomplete_and_provider_error_are_safe_and_not_cached(self):
        for response in (sdk_response(None),
                         sdk_response(None, status='incomplete'), RuntimeError('secret-key')):
            self.client.responses.create.side_effect = response if isinstance(response, Exception) else None
            self.client.responses.create.return_value = response
            with self.assertRaises(AnalysisFailure) as error:
                self.generate()
            self.assertNotIn('secret-key', str(error.exception))
            self.assertEqual(self.db['semantic_analyses'].rows[0]['status'], 'failed')
        self.client.responses.create.side_effect = None
        self.client.responses.create.return_value = sdk_response(output())
        self.assertFalse(self.generate()['reused'])
        self.assertEqual(len(self.db['semantic_analyses'].rows), 1)

    def test_unknown_ids_fabricated_quotes_missing_evidence_and_scores_rejected(self):
        invalid = []
        value = output(); value['themes'][0]['publication_ids'] = ['foreign']; invalid.append(value)
        value = output(); value['summary']['evidence'][0]['quote'] = 'Invented quote'; invalid.append(value)
        value = output(); value['summary']['evidence'] = []; invalid.append(value)
        value = output(); value['scores'] = {'openness': 99}; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_interpretation(value, self.texts)

    def test_no_valid_texts_or_over_budget_never_calls_provider(self):
        for texts in ([], [{'publication_id': '100', 'description': 'a' * 24001}]):
            with self.assertRaises(ValueError):
                self.analysis.generate(self.username, texts)
        self.factory.assert_not_called()

    def test_invalid_provider_json_is_not_persisted_as_completed(self):
        value = output()
        value['themes'][0]['evidence'][0]['quote'] = 'Not present in source'
        self.client.responses.create.return_value.output_text = json.dumps(value)
        with self.assertRaises(AnalysisFailure):
            self.generate()
        self.assertEqual(self.db['semantic_analyses'].rows[0]['status'], 'failed')
        self.assertNotIn('interpretation', self.db['semantic_analyses'].rows[0])

    def test_storage_reservation_failure_never_calls_provider(self):
        with patch.object(self.db['semantic_analyses'], 'update_one', side_effect=RuntimeError('private-uri')):
            with self.assertRaises(RuntimeError):
                self.generate()
        self.factory.assert_not_called()

    def test_model_and_prompt_versions_are_part_of_reuse_identity(self):
        self.generate()
        with patch('backend.semantic_analysis.PROMPT_VERSION', 'test-future-prompt'):
            self.assertEqual(self.analysis.latest(self.username, self.texts)['status'], 'stale')
            self.assertFalse(self.generate()['reused'])
        with patch('backend.semantic_analysis.ANALYSIS_MODEL', 'test-model-version'):
            self.assertFalse(self.generate()['reused'])
        self.assertEqual(self.client.responses.create.call_count, 3)

    def test_post_errors_are_mapped_without_credentials(self):
        db = Mock()
        db.__getitem__ = Mock(side_effect=self.db.__getitem__)
        with patch.object(semantic_routes, 'get_database', return_value=db), \
                patch.object(semantic_routes, 'SemanticAnalysis', return_value=self.analysis):
            self.client.responses.create.side_effect = RuntimeError('secret-key')
            status, result = asyncio.run(request('POST', '/api/semantics/testuser/analysis'))
            self.assertEqual(status, 502)
            self.assertNotIn('secret-key', str(result))
            self.db['semantic_analyses'].rows[0]['status'] = 'processing'
            status, _ = asyncio.run(request('POST', '/api/semantics/testuser/analysis'))
            self.assertEqual(status, 409)
            self.db['publications'].rows.clear()
            status, _ = asyncio.run(request('POST', '/api/semantics/testuser/analysis'))
            self.assertEqual(status, 422)

    def test_evaluation_absent_or_untrusted_has_no_scores(self):
        self.assertEqual(self.workspace.evaluation('testuser')['evaluation'], None)
        self.db['big_five_evaluations'].rows.append({'profile_username': 'TestUser',
            'source': 'openai', 'scores': {'openness': 99}})
        self.assertEqual(self.workspace.evaluation('testuser')['status'], 'unavailable')

    def test_only_valid_questionnaire_contract_exposes_scores(self):
        document = {'profile_username': 'TestUser', 'source': 'validated_questionnaire', 'status': 'validated',
            'instrument': {'name': 'BFI-2', 'version': 'documented-version'}, 'scoring_version': 'verified-v1',
            'completed_at': datetime.now(timezone.utc), 'scale': {'min': 0, 'max': 100},
            'scores': {key: 50 for key in semantic_routes.TRAITS}}
        self.db['big_five_evaluations'].rows.append(document)
        self.assertEqual(self.workspace.evaluation('testuser')['status'], 'available')
        for bad in (True, -1, 101, float('nan')):
            document['scores']['openness'] = bad
            self.assertEqual(self.workspace.evaluation('testuser')['status'], 'unavailable')

    def test_read_endpoints_and_safe_failures(self):
        db = Mock()
        db.__getitem__ = Mock(side_effect=self.db.__getitem__)
        with patch.object(semantic_routes, 'get_database', return_value=db):
            for path in ('map', 'analysis', 'big-five'):
                status, result = asyncio.run(request('GET', f'/api/semantics/testuser/{path}'))
                self.assertEqual(status, 200)
                self.assertEqual(result['profile_id'], 'testuser')
            status, _ = asyncio.run(request('GET', '/api/semantics/missing/map'))
            self.assertEqual(status, 404)
        self.assertEqual(db.client.close.call_count, 4)
        with patch.object(semantic_routes, 'get_database', side_effect=RuntimeError('private-uri')):
            status, result = asyncio.run(request('GET', '/api/semantics/testuser/map'))
            self.assertEqual(status, 503)
            self.assertNotIn('private-uri', str(result))

    def test_post_endpoint_is_explicit_and_reused(self):
        main.app.dependency_overrides[semantic_routes.semantic_workspace] = lambda: self.workspace
        try:
            with patch.object(semantic_routes, 'SemanticAnalysis', return_value=self.analysis):
                for reused in (False, True):
                    status, result = asyncio.run(request('POST', '/api/semantics/testuser/analysis'))
                    self.assertEqual(status, 200)
                    self.assertEqual(result['reused'], reused)
            self.assertEqual(self.client.responses.create.call_count, 1)
        finally:
            main.app.dependency_overrides.clear()


if __name__ == '__main__':
    unittest.main()
