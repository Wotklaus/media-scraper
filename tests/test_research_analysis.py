"""Short, controlled regressions. Provider fixtures are NEVER application fallbacks."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.analysis_errors import AnalysisFailure
from backend.research_analysis import ResearchAnalysis, literal_quote, semantic_groups
from backend.analysis_errors import ResponseProblem
import backend.research_analysis as research_analysis
from backend.embeddings import DIMENSIONS
from research_fake import Database


STUDY_ID = '233a3985-c2d3-4f1e-b67a-b5c0e37a1659'
AI_STUDY_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


def fixture(count=37, study_id=STUDY_ID):
    database = Database()
    database['research_studies'].insert_one({'_id': study_id, 'status': 'exhausted'})
    rows = []
    for i in range(count):
        row = {'_id': f'{study_id}-test-{i}', 'study_id': study_id, 'record_key': f'{i:064d}',
            'publication_id': f'fixture-publication-{i % 4}', 'text': f'Comentario de laboratorio {i}',
            'source': 'tiktok', 'synthetic': False, 'record_kind': 'comment'}
        database['research_records'].insert_one(row)
        rows.append(row)
    output = {'annotations': [{'reference': f'c{i+1}', 'category': 'technical_question' if i < 2 else 'social_opinion',
        'quote': row['text'], 'reason': 'Propuesta de prueba', 'ambiguous': False, 'alternatives': []}
        for i, row in enumerate(rows)], 'group_labels': [{'group_id': 'g1', 'title': 'Grupo controlado'}],
        'findings': [{'kind': 'need', 'title': 'Necesidad de prueba', 'references': ['c1', 'c2']},
                     {'kind': 'faq', 'title': 'Pregunta de prueba', 'references': ['c1', 'c2']}],
        'recommendations': [{'activity': 'Comparar dos ejemplos en una actividad práctica.', 'references': ['c1', 'c2']}]}
    client = Mock()
    vector = [1.0] + [0.0] * (DIMENSIONS - 1)
    client.embeddings.create.return_value.data = [SimpleNamespace(index=i, embedding=vector) for i in range(count)]
    client.responses.create.return_value = SimpleNamespace(status='completed', output=[], output_text=json.dumps(output))
    factory = Mock(return_value=client)
    return database, client, factory, output


class ResearchAnalysisTests(unittest.TestCase):
    def test_literal_quotes_restore_only_source_format_and_unicode(self):
        cases = [
            ('¿Por qué cambia?', '"¿Por qué cambia?"', '¿Por qué cambia?'),
            ('Línea 1\nLínea 2', '"Línea 1\\nLínea 2"', 'Línea 1\nLínea 2'),
            ('Dijo "hola"', '"Dijo \\"hola\\""', 'Dijo "hola"'),
            ('Una   respuesta\tútil.', '"Una respuesta útil."', 'Una   respuesta\tútil.'),
            ('¿Por que\u0301?', '"¿Por qué?"', '¿Por que\u0301?'),
        ]
        for original, proposal, expected in cases:
            with self.subTest(proposal=proposal):
                self.assertEqual(literal_quote(original, proposal), expected)
                self.assertIn(literal_quote(original, proposal), original)

    def test_invented_paraphrase_and_quote_from_another_comment_are_rejected(self):
        for original, proposal in [('¿Cómo funciona?', '"Explícame el mecanismo"'),
                                   ('¿Qué pasó?', '"Que paso?"'),
                                   ('¿Qué pasó?', '"¿Qué pasó!"'),
                                   ('Comentario de este estudio', '"Texto de otra investigación"'),
                                   ('Comentario local', '"Comentario distinto"')]:
            with self.subTest(proposal=proposal), self.assertRaises(ResponseProblem):
                literal_quote(original, proposal)

    def test_other_study_quote_cannot_be_attached_to_local_reference(self):
        database, client, factory, output = fixture(2, STUDY_ID)
        database['research_studies'].insert_one({'_id': AI_STUDY_ID, 'status': 'exhausted'})
        database['research_records'].insert_one({'_id': 'foreign', 'study_id': AI_STUDY_ID,
            'record_key': 'foreign-key', 'publication_id': 'foreign-publication', 'text': 'Cita de otro estudio',
            'source': 'youtube', 'synthetic': False, 'record_kind': 'comment'})
        originals = deepcopy(database['research_records'].rows)
        output['annotations'][0]['quote'] = '"Cita de otro estudio"'
        client.responses.create.return_value.output_text = json.dumps(output)
        service = ResearchAnalysis(database, factory)
        with self.assertRaises(AnalysisFailure) as failure:
            service.generate(STUDY_ID)
        self.assertEqual(failure.exception.code, 'evidence_quote')
        self.assertEqual(service.latest(STUDY_ID)['status'], 'failed')
        self.assertNotIn('result', service.latest(STUDY_ID))
        self.assertEqual(database['research_records'].rows, originals)

    def test_single_reference_faq_is_omitted_with_warning(self):
        database, client, factory, output = fixture(2, STUDY_ID)
        output['findings'][1]['references'] = ['c1']
        client.responses.create.return_value.output_text = json.dumps(output)
        result = ResearchAnalysis(database, factory).generate(STUDY_ID)['result']
        self.assertEqual(len(result['comments']), 2)
        self.assertEqual([finding['kind'] for finding in result['findings']], ['need'])
        self.assertTrue(any('único comentario' in warning for warning in result['validation_warnings']))

    def test_full_pipeline_saves_separately_reuses_and_leaves_originals_unchanged(self):
        database, client, factory, _ = fixture()
        before = deepcopy(database['research_records'].rows)
        service = ResearchAnalysis(database, factory)
        self.assertEqual(service.latest(STUDY_ID)['status'], 'unavailable')
        factory.assert_not_called()
        result = service.generate(STUDY_ID)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(sum(result['result']['category_counts'].values()), 37)
        self.assertEqual(len(result['result']['comments']), 37)
        self.assertEqual(result['result']['findings'][0]['count'], 2)
        self.assertFalse(result['result']['human_validated'])
        self.assertFalse(result['result']['recommendations'][0]['external_resources_verified'])
        self.assertEqual(database['research_records'].rows, before)
        stored = database['research_analyses'].find_one({'study_id': STUDY_ID})
        self.assertEqual(len(stored['vectors']), 37)
        self.assertNotIn('vectors', result)
        self.assertEqual(service.latest(STUDY_ID)['status'], 'completed')
        self.assertEqual(service.generate(STUDY_ID)['status'], 'completed')
        self.assertEqual(client.embeddings.create.call_count, 1)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(client.embeddings.create.call_count, 1)

    def test_missing_empty_or_invalid_corpus_never_calls_provider(self):
        database, _, factory, _ = fixture()
        service = ResearchAnalysis(database, factory)
        with self.assertRaises(ValueError): service.generate('another-study')
        database['research_studies'].insert_one({'_id': AI_STUDY_ID, 'status': 'exhausted'})
        self.assertEqual(service.latest(AI_STUDY_ID)['comment_count'], 0)
        self.assertFalse(service.latest(AI_STUDY_ID)['eligible'])
        with self.assertRaises(ValueError): service.generate(AI_STUDY_ID)
        database['research_records'].rows[0]['text'] = ''
        with self.assertRaises(ValueError): service.generate(STUDY_ID)
        factory.assert_not_called()

    def test_75_comments_other_study_isolated_persisted_and_stale_after_change(self):
        database, client, factory, _ = fixture(75, AI_STUDY_ID)
        original = deepcopy(database['research_records'].rows)
        service = ResearchAnalysis(database, factory)
        self.assertEqual(service.latest(AI_STUDY_ID)['comment_count'], 75)
        self.assertTrue(service.latest(AI_STUDY_ID)['eligible'])
        output = service.generate(AI_STUDY_ID)
        self.assertEqual(output['status'], 'completed')
        self.assertEqual(output['comment_count'], 75)
        self.assertEqual(sum(output['result']['category_counts'].values()), 75)
        self.assertEqual(output['result']['comments'][0]['source'], 'tiktok')
        self.assertEqual(database['research_records'].rows, original)
        self.assertEqual(service.latest(AI_STUDY_ID)['status'], 'completed')
        self.assertEqual(database['research_analyses'].count_documents({'study_id': STUDY_ID}), 0)
        self.assertEqual(client.embeddings.create.call_count, 1)
        self.assertEqual(client.responses.create.call_count, 1)
        schema = client.responses.create.call_args.kwargs['text']['format']['schema']
        self.assertEqual(schema['properties']['annotations']['minItems'], 75)
        self.assertEqual(schema['properties']['annotations']['maxItems'], 75)
        database['research_records'].rows[0]['source'] = 'youtube'
        self.assertEqual(service.latest(AI_STUDY_ID)['status'], 'stale')
        database['research_records'].rows[0]['source'] = 'tiktok'
        database['research_records'].rows[0]['text'] += ' cambiado'
        self.assertEqual(service.latest(AI_STUDY_ID)['status'], 'stale')
        self.assertEqual(client.responses.create.call_count, 1)

    def test_explicit_limit_rejects_without_truncation_or_provider(self):
        database, _, factory, _ = fixture(75, AI_STUDY_ID)
        service = ResearchAnalysis(database, factory)
        with patch.dict('os.environ', {'RESEARCH_ANALYSIS_MAX_COMMENTS': '50'}):
            state = service.latest(AI_STUDY_ID)
            self.assertFalse(state['eligible'])
            self.assertEqual(state['comment_count'], 75)
            with self.assertRaises(ValueError): service.generate(AI_STUDY_ID)
        factory.assert_not_called()

    def test_general_questions_and_other_sources_preserve_provenance(self):
        database, client, factory, output = fixture(2, AI_STUDY_ID)
        database['research_records'].rows[0]['source'] = 'youtube'
        database['research_records'].rows[1]['source'] = 'synthetic'
        database['research_records'].rows[1]['synthetic'] = True
        for annotation in output['annotations']:
            annotation['category'] = 'general_question'
        client.responses.create.return_value.output_text = json.dumps(output)
        result = ResearchAnalysis(database, factory).generate(AI_STUDY_ID)['result']
        self.assertEqual(result['category_counts']['general_question'], 2)
        self.assertEqual(len(result['recommendations']), 1)
        self.assertEqual(result['comments'][0]['source'], 'youtube')
        self.assertTrue(result['comments'][1]['synthetic'])

    def test_forged_quote_fails_without_publishing_partial_results_and_can_retry(self):
        database, client, factory, output = fixture()
        output['annotations'][0]['quote'] = 'Invented SECRET'
        client.responses.create.return_value.output_text = json.dumps(output)
        service = ResearchAnalysis(database, factory)
        with self.assertRaises(AnalysisFailure): service.generate(STUDY_ID)
        result = service.latest(STUDY_ID)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('result', result)
        self.assertNotIn('SECRET', str(result))
        output['annotations'][0]['quote'] = 'Comentario de laboratorio 0'
        client.responses.create.return_value.output_text = json.dumps(output)
        self.assertEqual(service.generate(STUDY_ID)['status'], 'completed')

    def test_invented_resources_and_cross_record_references_are_rejected(self):
        for mutation in ('resource', 'reference'):
            database, client, factory, output = fixture()
            if mutation == 'resource': output['recommendations'][0]['activity'] = 'Visita https://invented.invalid/curso'
            if mutation == 'reference': output['findings'][0]['references'] = ['c999']
            client.responses.create.return_value.output_text = json.dumps(output)
            with self.subTest(mutation=mutation), self.assertRaises(AnalysisFailure):
                ResearchAnalysis(database, factory).generate(STUDY_ID)

    def test_unsupported_educational_claims_are_omitted_with_explicit_warnings(self):
        database, client, factory, output = fixture()
        output['annotations'][0]['category'] = 'commercial_request'
        client.responses.create.return_value.output_text = json.dumps(output)
        result = ResearchAnalysis(database, factory).generate(STUDY_ID)['result']
        self.assertEqual(len(result['comments']), 37)
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['recommendations'], [])
        self.assertTrue(result['validation_warnings'])

    def test_grouping_is_complete_link_not_transitive_chaining(self):
        groups = semantic_groups([[1, 0], [0.8, 0.6], [0, 1]])
        self.assertEqual([g['references'] for g in groups], [['c1', 'c2'], ['c3']])
        self.assertEqual(groups[0]['minimum_similarity'], 0.8)

    def test_changed_threshold_reuses_vectors_for_identical_corpus(self):
        database, client, factory, _ = fixture()
        service = ResearchAnalysis(database, factory)
        self.assertEqual(service.generate(STUDY_ID)['status'], 'completed')
        with patch.object(research_analysis, 'THRESHOLD', 0.62):
            self.assertEqual(service.generate(STUDY_ID)['status'], 'completed')
        self.assertEqual(client.embeddings.create.call_count, 1)
        self.assertEqual(client.responses.create.call_count, 2)
        self.assertEqual(database['research_analyses'].count_documents({'study_id': STUDY_ID}), 2)

    def test_previously_saved_v1_analysis_is_read_without_regeneration(self):
        database, client, factory, _ = fixture()
        service = ResearchAnalysis(database, factory)
        with patch.object(research_analysis, 'VERSION', research_analysis.LEGACY_VERSION):
            self.assertEqual(service.generate(STUDY_ID)['status'], 'completed')
        saved = service.latest(STUDY_ID)
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['version'], research_analysis.LEGACY_VERSION)
        self.assertEqual(saved['comment_count'], 37)
        self.assertEqual(service.generate(STUDY_ID)['status'], 'completed')
        self.assertEqual(client.responses.create.call_count, 1)

    def test_generic_learning_resources_are_not_mistaken_for_invented_courses(self):
        database, client, factory, output = fixture()
        output['recommendations'][0]['activity'] = 'Comparar recursos disponibles en una actividad práctica.'
        output['annotations'][0]['alternatives'] = ['technical_question', 'insufficient_context', 'insufficient_context']
        client.responses.create.return_value.output_text = json.dumps(output)
        result = ResearchAnalysis(database, factory).generate(STUDY_ID)['result']
        self.assertEqual(result['comments'][0]['alternatives'], ['insufficient_context'])
        self.assertTrue(result['comments'][0]['ambiguous'])
