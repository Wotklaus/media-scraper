"""No provider/DB connections. The optional snapshot is read-only and never committed."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from backend.semantic_analysis import SemanticAnalysis, validate_interpretation, Finding, validate_finding
from backend.ocean_analysis import OceanAnalysis
from backend.structured_analysis import literal_fragments, source_schema
from backend.semantic_analysis import Interpretation
from backend.analysis_errors import AnalysisFailure
from test_embeddings import fixture
from test_semantics import AnalysisCollection, sdk_response


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.db, _, _, _ = fixture(2)
        self.db['semantic_analyses'] = AnalysisCollection()
        self.db['ocean_analyses'] = AnalysisCollection()
        self.rows = [{'publication_id': '7698141302722006293', 'description': 'Mercados: ideas, riesgos y decisiones. 🎵'},
                     {'publication_id': '7697711191287745813', 'description': 'Exploracio\u0301n\u00a0de ideas\nfinancieras.'}]
        self.client = Mock()
        self.service = SemanticAnalysis(self.db, Mock(return_value=self.client))
        self.block = patch('backend.embeddings.OpenAI', side_effect=AssertionError('Paid calls forbidden'))
        self.block.start(); self.addCleanup(self.block.stop)

    def finding(self, reference='p1', quote=None):
        return {'text': 'Mención explícita de mercados.', 'publication_ids': [reference],
                'evidence': [{'publication_id': reference, 'quote': quote or literal_fragments(self.rows[0]['description'])[0]}]}

    def generate(self, value, service=None):
        self.client.responses.create.return_value = sdk_response(value)
        return (service or self.service).generate('zonaatrading', self.rows)

    def test_wire_schema_binds_quote_choices_to_the_same_alias_and_full_source(self):
        value = {'summary': self.finding(), 'themes': [], 'communication_style': []}
        self.generate(value)
        args = self.client.responses.create.call_args.kwargs
        sources = json.loads(args['input'])
        self.assertEqual(sources[0]['text'], self.rows[0]['description'].strip())
        self.assertEqual(sources[0]['evidence_quotes'], literal_fragments(self.rows[0]['description']))
        variants = args['text']['format']['schema']['$defs']['Evidence']['anyOf']
        for row, variant, source in zip(self.rows, variants, sources):
            self.assertEqual(variant['properties']['publication_id']['enum'], [source['publication_id']])
            self.assertEqual(variant['properties']['quote']['enum'], source['evidence_quotes'])
            for quote in source['evidence_quotes']:
                self.assertIn(quote, row['description']); self.assertLessEqual(len(quote), 79)

    def test_valid_alias_restoration_and_partial_rejections_are_counted(self):
        value = {'summary': self.finding(), 'themes': [], 'communication_style': [self.finding('unknown')]}
        result = self.generate(value)
        audit = self.db['semantic_analyses'].rows[0]['validation']
        self.assertEqual((audit['received'],audit['accepted'],audit['rejected']), (2,1,1))
        self.assertEqual(audit['reasons'], {'evidence_reference':1})
        self.assertTrue(result['analysis']['interpretation']['partial'])
        self.assertNotIn(self.rows[0]['description'], json.dumps(audit))

    def test_legitimate_no_findings_is_distinct_from_all_rejected_evidence(self):
        empty = {'summary':None,'themes':[],'communication_style':[]}
        result = self.generate(empty)
        self.assertEqual(result['analysis']['interpretation']['evidence_status'], 'insufficient_evidence')
        self.assertEqual(self.db['semantic_analyses'].rows[0]['validation']['received'],0)
        self.assertTrue(self.service.generate('zonaatrading',self.rows)['reused'])
        self.rows[0]['description'] += '!'
        bad = {'summary':self.finding(quote='Invented quotation'),'themes':[],'communication_style':[]}
        with self.assertRaises(AnalysisFailure): self.generate(bad)
        failure = self.db['semantic_analyses'].rows[1]['failure']
        self.assertEqual(failure['validation']['reasons'], {'evidence_quote':1})
        self.assertEqual(failure['validation']['received'],1)

    def test_unicode_canonical_equivalence_passes_but_spelling_changes_do_not(self):
        evidence = self.finding(self.rows[1]['publication_id'], 'Exploración de ideas financieras.')
        validate_finding(evidence, Finding, self.rows)
        evidence['evidence'][0]['quote'] = 'Exploración de conceptos financieros.'
        with self.assertRaises(ValueError): validate_finding(evidence, Finding, self.rows)

    def test_fragments_never_add_ellipsis_or_change_the_source(self):
        for text in ['a'*170, '¿Confías… en el proceso? 🎵 '*15, '\n  Hola\u00a0mundo  \n', '']:
            for fragment in literal_fragments(text):
                self.assertIn(fragment,text); self.assertLessEqual(len(fragment),79)

    def test_ocean_zero_indicators_is_valid_absence_not_integration_failure(self):
        service = OceanAnalysis(self.db, client_factory=Mock(return_value=self.client))
        from backend.ocean_analysis import DIMENSION_NAMES
        value = {'dimensions':[{'dimension':key,'description':'Evidencia insuficiente','indicators':[]} for key in DIMENSION_NAMES]}
        report = self.generate(value, service)['analysis']['interpretation']
        self.assertTrue(all(row['status']=='insufficient_evidence' for row in report['dimensions']))
        self.assertEqual(self.db['ocean_analyses'].rows[0]['validation']['received'],0)

    def test_quote_from_another_source_is_rejected_and_diagnosed_without_text(self):
        quote = literal_fragments(self.rows[0]['description'])[0]
        value = {'summary':self.finding('p2',quote),'themes':[],'communication_style':[]}
        with self.assertRaises(AnalysisFailure): self.generate(value)
        audit = self.db['semantic_analyses'].rows[0]['failure']['validation']
        check = audit['items'][0]['quote_checks'][0]
        self.assertFalse(check['same_source_match'])
        self.assertTrue(check['other_source_match'])
        self.assertNotIn(quote,json.dumps(audit,ensure_ascii=False))

    def test_schema_diagnostics_redact_arbitrary_model_keys(self):
        finding = self.finding(); finding['synthetic-private-key'] = 'synthetic-private-value'
        value = {'summary':finding,'themes':[],'communication_style':[]}
        with self.assertRaises(AnalysisFailure): self.generate(value)
        audit = self.db['semantic_analyses'].rows[0]['failure']['validation']
        self.assertEqual(audit['reasons'],{'output_schema':1})
        self.assertEqual(audit['items'][0]['schema_issues'][0]['path'],['<field>'])
        self.assertNotIn('synthetic-private',json.dumps(audit))

    def test_http_empty_result_and_invalid_evidence_remain_distinct(self):
        import asyncio
        from backend import semantic_routes
        from test_embeddings import request
        self.db['publications'].rows = [{**row, 'profile_username': 'TestUser'} for row in self.rows]
        db = Mock(); db.__getitem__ = Mock(side_effect=self.db.__getitem__)
        with patch.object(semantic_routes, 'get_database', return_value=db), patch.object(semantic_routes, 'SemanticAnalysis', return_value=self.service):
            self.client.responses.create.return_value = sdk_response({'summary':None,'themes':[],'communication_style':[]})
            status, result = asyncio.run(request('POST', '/api/semantics/testuser/analysis'))
            self.assertEqual(status,200)
            self.assertEqual(result['analysis']['interpretation']['evidence_status'],'insufficient_evidence')
            self.db['publications'].rows[0]['description'] += '!'
            self.client.responses.create.return_value = sdk_response({'summary':self.finding(quote='Invented quote'),'themes':[],'communication_style':[]})
            status, result = asyncio.run(request('POST', '/api/semantics/testuser/analysis'))
            self.assertEqual(status,502)
            self.assertEqual(result['detail']['code'],'evidence_missing')
            self.assertEqual(self.db['semantic_analyses'].rows[-1]['failure']['validation']['rejected'],1)

    def test_official_sdk_serializes_per_source_quote_variants_without_network(self):
        from test_ocean import SDKRegressionTests, envelope
        requests = []
        value = {'summary':self.finding(),'themes':[],'communication_style':[]}
        with SDKRegressionTests().client(envelope(payload=json.dumps(value)), requests) as client:
            self.service.client_factory = Mock(return_value=client)
            result = self.service.generate('zonaatrading', self.rows)
        self.assertEqual(result['status'],'current')
        self.assertEqual(len(requests),1)
        variants = requests[0]['text']['format']['schema']['$defs']['Evidence']['anyOf']
        self.assertEqual(variants[0]['properties']['quote']['enum'],literal_fragments(self.rows[0]['description']))


class StoredSourceReproduction(SourceEvidenceTests):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = Path('/tmp/zonatrading-sources.json')
        if not cls.snapshot.is_file():
            raise unittest.SkipTest('Read-only MongoDB snapshot unavailable; synthetic cases still run')

    def setUp(self):
        super().setUp()
        self.rows = json.loads(self.snapshot.read_text())

    def test_unicode_canonical_equivalence_passes_but_spelling_changes_do_not(self):
        # Unicode-specific assertions are exercised by the synthetic case above.
        quote = self.rows[0]['description'][:60]
        validate_finding(self.finding(self.rows[0]['publication_id'],quote),Finding,self.rows)

    def test_stored_sources_reproduce_old_quote_rejection_without_id_mapping_error(self):
        # Representative response, not the unavailable historical provider payload.
        value = {'summary':self.finding(quote=self.rows[0]['description'][:65]+'...'), 'themes':[], 'communication_style':[]}
        with self.assertRaises(AnalysisFailure): self.generate(value)
        audit = self.db['semantic_analyses'].rows[0]['failure']['validation']
        self.assertEqual(audit['known_reference'],1)
        self.assertEqual(audit['reasons'],{'evidence_quote':1})
        self.db['semantic_analyses'].rows.clear()  # In-memory fake only.
        quote = literal_fragments(self.rows[0]['description'])[0]
        value['summary'] = self.finding(quote=quote)
        self.generate(value)
        audit = self.db['semantic_analyses'].rows[0]['validation']
        self.assertEqual((audit['received'],audit['accepted'],audit['rejected']),(1,1,0))
