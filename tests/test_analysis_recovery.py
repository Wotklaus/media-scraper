"""Offline regressions for reference transport and conservative partial recovery."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from backend.analysis_errors import AnalysisFailure
from backend.semantic_analysis import SemanticAnalysis, Interpretation
from backend.ocean_analysis import OceanAnalysis
from backend.structured_analysis import source_schema, request_structured
import test_semantics as semantic
import test_ocean as ocean
from test_embeddings import fixture


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.db, _, _, _ = fixture(3)
        self.db['semantic_analyses'] = semantic.AnalysisCollection()
        self.db['ocean_analyses'] = semantic.AnalysisCollection()
        self.texts = [{'publication_id': '7541234567890123456', 'description': 'Exploro ideas nuevas 🎵'},
                      {'publication_id': '7541234567890123457', 'description': 'Gracias por ayudar\na explorar ideas'}]
        self.client = Mock()
        self.factory = Mock(return_value=self.client)
        self.service = SemanticAnalysis(self.db, self.factory)
        self.ocean = OceanAnalysis(self.db, client_factory=self.factory)
        self.block = patch('backend.embeddings.OpenAI', side_effect=AssertionError('Live OpenAI forbidden'))
        self.block.start()
        self.addCleanup(self.block.stop)

    def finding(self, id='p1', quote='Exploro ideas nuevas 🎵'):
        return {'text': 'Expresión de exploración.', 'publication_ids': [id],
                'evidence': [{'publication_id': id, 'quote': quote}]}

    def content(self):
        return {'summary': self.finding(), 'themes': [], 'communication_style': [self.finding()]}

    def generate(self, value, service=None):
        self.client.responses.create.return_value = semantic.sdk_response(value)
        return (service or self.service).generate('TestUser', self.texts)

    def test_long_ids_never_enter_provider_input_and_are_restored_before_storage(self):
        result = self.generate(self.content())
        args = self.client.responses.create.call_args.kwargs
        self.assertEqual(json.loads(args['input'])[0]['publication_id'], 'p1')
        self.assertNotIn('7541234567890123456', args['input'])
        schema = args['text']['format']['schema']
        self.assertEqual(schema['$defs']['Evidence']['anyOf'][0]['properties']['publication_id']['enum'], ['p1'])
        self.assertEqual(schema['$defs']['Finding']['properties']['publication_ids']['items']['enum'], ['p1', 'p2'])
        self.assertEqual(result['analysis']['interpretation']['summary']['publication_ids'], [self.texts[0]['publication_id']])
        self.assertEqual(self.db['semantic_analyses'].rows[0]['interpretation'], result['analysis']['interpretation'])
        self.assertTrue(self.service.generate('TestUser', self.texts)['reused'])
        self.assertEqual(self.client.responses.create.call_count, 1)

    def test_invalid_summary_does_not_destroy_independent_valid_finding(self):
        value = self.content(); value['summary']['evidence'][0]['quote'] = 'inventado'
        report = self.generate(value)['analysis']['interpretation']
        self.assertIsNone(report['summary']); self.assertTrue(report['partial'])
        self.assertEqual(len(report['communication_style']), 1)
        self.assertEqual(self.service.latest('TestUser', self.texts)['analysis']['interpretation'], report)

    def test_invalid_schema_in_one_finding_is_discarded_without_losing_other_findings(self):
        value = self.content(); value['communication_style'][0]['text'] = 'x' * 281
        report = self.generate(value)['analysis']['interpretation']
        self.assertEqual(report['communication_style'], [])
        self.assertIsNotNone(report['summary']); self.assertTrue(report['partial'])

    def test_missing_one_reference_discards_whole_claim_not_just_bad_citation(self):
        value = self.content(); value['summary']['publication_ids'].append('p2')
        report = self.generate(value)['analysis']['interpretation']
        self.assertIsNone(report['summary'])
        self.assertNotIn('p2', str(report))

    def test_nothing_verifiable_is_failed_and_not_cached_as_completed(self):
        value = self.content()
        for finding in [value['summary'], *value['communication_style']]:
            finding['evidence'][0]['publication_id'] = 'foreign'
        with self.assertRaises(AnalysisFailure) as error:
            self.generate(value)
        self.assertEqual(error.exception.code, 'evidence_missing')
        self.assertEqual(self.db['semantic_analyses'].rows[0]['status'], 'failed')
        self.assertNotIn('interpretation', self.db['semantic_analyses'].rows[0])
        self.assertEqual(self.client.responses.create.call_count, 1)

    def test_whitespace_and_unicode_composition_are_not_confused_with_invention(self):
        self.texts[0]['description'] = 'Exploracio\u0301n\u00a0de\nideas 🎵'
        value = self.content()
        for finding in [value['summary'], *value['communication_style']]:
            finding['evidence'][0]['quote'] = 'Exploración de ideas 🎵'
        self.assertFalse(self.generate(value)['analysis']['interpretation']['partial'])

    def test_ocean_recovers_valid_indicators_and_marks_other_dimensions_insufficient(self):
        indicator = {'name': 'Exploración', 'description': 'Expresión de exploración.',
                     'publication_ids': ['p1'], 'evidence': self.finding()['evidence']}
        value = {'dimensions': [{'dimension': 'openness', 'description': 'Exploración.',
                                'indicators': [deepcopy(indicator), {**indicator, 'publication_ids': ['foreign']}]},
                               {'dimension': 'agreeableness', 'description': 'Apoyo explícito.',
                                'indicators': [{**indicator, 'publication_ids': ['p2'],
                                    'evidence': [{'publication_id': 'p2', 'quote': 'Gracias por ayudar'}]}]}]}
        report = self.generate(value, self.ocean)['analysis']['interpretation']
        self.assertTrue(report['partial']); self.assertEqual(len(report['dimensions']), 5)
        self.assertEqual(len(report['dimensions'][0]['indicators']), 1)
        self.assertEqual(report['dimensions'][0]['support_count'], 1)
        self.assertIsNone(report['dimensions'][0]['presence_index'])
        self.assertEqual(report['dimensions'][1]['indicators'], [])
        self.assertEqual(self.ocean.latest('TestUser', self.texts)['analysis']['interpretation'], report)

    def test_invalid_source_ids_fail_before_client_or_storage(self):
        for bad_id in (None, '', 7541234567890123456):
            with self.subTest(id=bad_id), self.assertRaises(ValueError):
                self.service.generate('TestUser', [{**self.texts[0], 'publication_id': bad_id}])
        with self.assertRaises(ValueError):
            self.service.generate('TestUser', [self.texts[0], self.texts[0]])
        self.factory.assert_not_called()
        self.assertEqual(self.db['semantic_analyses'].rows, [])

    def test_sdk_transport_uses_real_serialization_with_alias_enum_offline(self):
        requests = []
        # MockTransport handles this SDK request in process; no sockets or billing.
        with ocean.SDKRegressionTests().client(ocean.envelope(payload=json.dumps(self.content())), requests) as client:
            value = request_structured(client, model='gpt-5.4-mini-2026-03-17', schema=Interpretation,
                instructions='synthetic only', input_text='synthetic only', references=['p1', 'p2'], raw=True)
        self.assertEqual(value, self.content()); self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['text']['format']['schema'], source_schema(Interpretation, ['p1', 'p2']))


if __name__ == '__main__':
    unittest.main()
