"""Offline OCEAN and SDK regressions. No API keys, Atlas or browser are used."""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bson import BSON
import httpx2
from openai import OpenAI, BadRequestError, AuthenticationError, APITimeoutError, RateLimitError
from pydantic import ValidationError

from backend import semantic_routes
from backend.analysis_errors import diagnostic, AnalysisFailure, ResponseProblem
from backend.ocean_analysis import OceanAnalysis, OceanSignals, DIMENSION_NAMES
from backend.semantic_analysis import Interpretation, SemanticAnalysis, ANALYSIS_MODEL
from backend.structured_analysis import request_structured
from test_embeddings import fixture, request
from test_semantics import AnalysisCollection, output, sdk_response


def ocean_output(supported=False):
    indicator = {'name': 'Exploración explícita de ideas', 'description': 'El texto propone explorar ideas.',
        'publication_ids': ['100', '101'], 'evidence': [
            {'publication_id': '100', 'quote': 'Descripción 0'},
            {'publication_id': '101', 'quote': 'Descripción 1'}]}
    return {'dimensions': [{'dimension': key, 'description': 'Señales observables' if supported else 'Evidencia insuficiente',
                            'indicators': [deepcopy(indicator)] if supported and key == 'openness' else []}
                           for key in DIMENSION_NAMES]}


def envelope(status='completed', payload=None, refusal=False):
    content = ([{'type': 'refusal', 'refusal': 'mock refusal'}] if refusal else
               [{'type': 'output_text', 'text': payload, 'annotations': []}])
    return {'id': 'resp_mock', 'object': 'response', 'created_at': 0, 'status': status,
        'model': ANALYSIS_MODEL, 'output': [{'type': 'message', 'id': 'msg_mock',
            'status': status, 'role': 'assistant', 'content': content}],
        'incomplete_details': {'reason': 'max_output_tokens'} if status == 'incomplete' else None}


class SDKRegressionTests(unittest.TestCase):
    def client(self, body, requests=None):
        def transport(request):
            if requests is not None:
                requests.append(json.loads(request.content))
            return httpx2.Response(200, json=body)
        return OpenAI(api_key='synthetic-offline-only', max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))

    def test_installed_sdk_parse_raises_before_status_for_truncated_json(self):
        with self.client(envelope('incomplete', '{"summary":')) as client:
            with self.assertRaises(ValidationError):
                client.responses.parse(model=ANALYSIS_MODEL, input='synthetic', text_format=Interpretation)

    def test_fixed_flow_checks_incomplete_before_json_validation(self):
        with self.client(envelope('incomplete', '{"summary":')) as client:
            with self.assertRaises(ResponseProblem) as error:
                request_structured(client, model=ANALYSIS_MODEL, schema=Interpretation,
                                   instructions='synthetic', input_text='synthetic')
            self.assertEqual(error.exception.code, 'output_truncated')

    def test_official_sdk_serializes_schema_and_validates_success_offline(self):
        requests = []
        with self.client(envelope(payload=json.dumps(output())), requests) as client:
            result = request_structured(client, model=ANALYSIS_MODEL, schema=Interpretation,
                                        instructions='synthetic', input_text='synthetic')
        self.assertIsInstance(result, Interpretation)
        self.assertTrue(requests[0]['text']['format']['strict'])
        self.assertEqual(requests[0]['text']['format']['schema'], Interpretation.model_json_schema())
        self.assertEqual(requests[0]['model'], ANALYSIS_MODEL)
        self.assertEqual(len(requests), 1)

    def test_refusal_and_completed_invalid_json_are_distinct(self):
        with self.client(envelope(payload='', refusal=True)) as client:
            with self.assertRaises(ResponseProblem) as error:
                request_structured(client, model=ANALYSIS_MODEL, schema=Interpretation,
                                   instructions='synthetic', input_text='synthetic')
            self.assertEqual(error.exception.code, 'output_refused')
        with self.client(envelope(payload='{"summary":')) as client:
            with self.assertRaises(ValidationError):
                request_structured(client, model=ANALYSIS_MODEL, schema=Interpretation,
                                   instructions='synthetic', input_text='synthetic')

    def test_allowlisted_diagnostics_never_log_error_bodies_or_secrets(self):
        request = httpx2.Request('POST', 'https://api.openai.com/v1/responses')
        response = httpx2.Response(400, request=request)
        cases = [
            (BadRequestError('secret-key description', response=response, body={'code': 'invalid_json_schema'}), 'invalid_schema'),
            (BadRequestError('secret-key description', response=response, body={'code': 'model_not_found'}), 'model_unavailable'),
            (AuthenticationError('secret-key', response=response, body={}), 'authentication'),
            (RateLimitError('secret-key', response=response, body={}), 'rate_limit'),
            (APITimeoutError(request=request), 'timeout'),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected), self.assertLogs('backend.analysis_errors', level='WARNING') as logs:
                failure = diagnostic(error, 'provider', ANALYSIS_MODEL)
            self.assertEqual(failure.code, expected)
            self.assertIn(failure.reference, str(logs.output))
            self.assertNotIn('secret-key', str(logs.output) + json.dumps(failure.public()))
            self.assertNotIn('description', str(logs.output))


class OceanTests(unittest.TestCase):
    def setUp(self):
        self.db, _, _, _ = fixture(3)
        self.db['semantic_analyses'] = AnalysisCollection()
        self.db['ocean_analyses'] = AnalysisCollection()
        self.client = Mock()
        self.client.responses.create.return_value = sdk_response(ocean_output(True))
        self.factory = Mock(return_value=self.client)
        self.service = OceanAnalysis(self.db, client_factory=self.factory)
        self.workspace = semantic_routes.SemanticWorkspace(self.db)
        self.username, self.texts = self.workspace.valid_texts('testuser')

    def generate(self, **kwargs):
        return self.service.generate(self.username, self.texts, **kwargs)

    def test_indices_are_computed_from_unique_evidence_not_model_numbers(self):
        result = self.generate()['analysis']['interpretation']['dimensions']
        self.assertEqual([row['name'] for row in result], list(DIMENSION_NAMES.values()))
        self.assertEqual(result[0]['support_count'], 2)
        self.assertEqual(result[0]['total_count'], 3)
        self.assertEqual(result[0]['presence_index'], 66.7)
        self.assertTrue(all(row['presence_index'] is None for row in result[1:]))
        self.assertNotIn('scores', str(result))

    def test_one_publication_is_insufficient_even_with_multiple_indicators(self):
        value = ocean_output(True)
        indicator = value['dimensions'][0]['indicators'][0]
        indicator['publication_ids'] = ['100']; indicator['evidence'] = indicator['evidence'][:1]
        value['dimensions'][0]['indicators'].append(deepcopy(indicator))
        report = self.service.validate(value, self.texts)
        row = report['dimensions'][0]
        self.assertEqual(row['status'], 'insufficient_evidence')
        self.assertEqual(row['support_count'], 1)
        self.assertIsNone(row['presence_index'])

    def test_no_signals_is_explicit_and_never_invents_scores(self):
        rows = self.service.validate(ocean_output(), self.texts)['dimensions']
        self.assertTrue(all(row['status'] == 'insufficient_evidence' and row['presence_index'] is None for row in rows))

    def test_model_supplied_scores_unknown_ids_and_invented_quotes_are_rejected(self):
        values = []
        value = ocean_output(True); value['dimensions'][0]['presence_index'] = 99; values.append(value)
        value = ocean_output(True); value['dimensions'][0]['indicators'][0]['publication_ids'] = ['other']; values.append(value)
        value = ocean_output(True); value['dimensions'][0]['indicators'][0]['evidence'][0]['quote'] = 'Fabricated'; values.append(value)
        value = ocean_output(); value['dimensions'][0]['dimension'] = 'neuroticism'; values.append(value)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.service.validate(value, self.texts)

    def test_stored_indices_are_recomputed_from_evidence(self):
        value = self.service.validate(ocean_output(True), self.texts)
        value['dimensions'][0]['presence_index'] = 99
        self.assertEqual(self.service.validate(value, self.texts, stored=True)['dimensions'][0]['presence_index'], 66.7)

    def test_get_and_repeated_post_reuse_without_paid_calls(self):
        self.assertEqual(self.service.latest(self.username, self.texts)['status'], 'empty')
        self.factory.assert_not_called()
        first = self.generate()
        self.assertTrue(self.generate()['reused'])
        self.assertEqual(self.service.latest(self.username, self.texts)['analysis'], first['analysis'])
        self.assertEqual(self.client.responses.create.call_count, 1)
        self.assertEqual(len(self.db['ocean_analyses'].rows), 1)
        BSON.encode(self.db['ocean_analyses'].rows[0])

    def test_content_and_profiles_are_isolated(self):
        self.generate()
        self.assertEqual(self.service.latest('other', self.texts)['status'], 'empty')
        self.texts[2]['description'] = 'Updated content'
        self.assertEqual(self.service.latest(self.username, self.texts)['status'], 'stale')
        self.assertFalse(self.generate()['reused'])

    def test_explicit_regeneration_preserves_previous_revision(self):
        first = self.generate()
        second = self.generate(regenerate=True)
        self.assertFalse(second['reused'])
        self.assertEqual(self.client.responses.create.call_count, 2)
        revisions = [row for row in self.db['ocean_analyses'].rows if 'revision_of' in row]
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0]['interpretation'], first['analysis']['interpretation'])

    def test_failed_regeneration_keeps_previous_result_available(self):
        first = self.generate()
        self.client.responses.create.side_effect = RuntimeError('secret-key')
        with self.assertRaises(AnalysisFailure):
            self.generate(regenerate=True)
        self.assertEqual(self.service.latest(self.username, self.texts)['analysis'], first['analysis'])
        self.assertTrue(self.generate()['reused'])

    def test_three_services_never_write_to_embeddings_or_extraction_data(self):
        before = {key: deepcopy(self.db[key].rows) for key in ('embeddings', 'profiles', 'publications')}
        self.generate()
        self.service.latest(self.username, self.texts)
        self.assertEqual(before, {key: self.db[key].rows for key in before})
        self.assertEqual(self.db['semantic_analyses'].rows, [])

    def test_nine_existing_vectors_are_reused_unchanged(self):
        db, client, factory, service = fixture(9)
        service.generate('testuser')
        before = deepcopy(db['embeddings'].rows)
        factory.reset_mock()
        client.embeddings.create.reset_mock()
        result = service.generate('testuser')
        self.assertEqual((result['generated'], result['reused']), (0, 9))
        self.assertEqual(db['embeddings'].rows, before)
        factory.assert_not_called()
        client.embeddings.create.assert_not_called()

    def test_concurrent_regeneration_reuses_old_result_for_reads_without_extra_calls(self):
        previous = self.generate()
        def respond(**kwargs):
            stored = self.service.latest(self.username, self.texts)
            self.assertTrue(stored['processing'])
            self.assertEqual(stored['analysis'], previous['analysis'])
            self.assertTrue(self.generate()['reused'])
            from backend.semantic_analysis import AnalysisBusy
            with self.assertRaises(AnalysisBusy):
                self.generate(regenerate=True)
            return sdk_response(ocean_output(True))
        self.client.responses.create.side_effect = respond
        self.generate(regenerate=True)
        self.assertEqual(self.client.responses.create.call_count, 2)

    def test_get_route_is_read_only_and_regenerate_requires_cost_confirmation(self):
        db = Mock(); db.__getitem__ = Mock(side_effect=self.db.__getitem__)
        with patch.object(semantic_routes, 'get_database', return_value=db), \
                patch.object(semantic_routes, 'OceanAnalysis', return_value=self.service):
            status, result = asyncio.run(request('GET', '/api/semantics/testuser/ocean'))
            self.assertEqual((status, result['status']), (200, 'empty'))
            self.factory.assert_not_called()
            status, _ = asyncio.run(request('POST', '/api/semantics/testuser/ocean', body=b'{"regenerate":true}'))
            self.assertEqual(status, 422)
            self.factory.assert_not_called()
            for body in (b'', b'', b'{"regenerate":true,"confirm_cost":true}'):
                status, result = asyncio.run(request('POST', '/api/semantics/testuser/ocean', body=body))
                self.assertEqual(status, 200)
            self.assertEqual(self.client.responses.create.call_count, 2)


if __name__ == '__main__':
    unittest.main()
