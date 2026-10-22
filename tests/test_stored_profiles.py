"""Read-only profile workspace, tested without Atlas, OpenAI or Chromium."""

import asyncio
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from backend import main, stored_profiles
from backend.embeddings import MODEL
from test_embeddings import fixture, request


class StoredProfilesTests(unittest.TestCase):
    def setUp(self):
        self.db, self.client, self.factory, self.generator = fixture()
        self.db['profiles'].rows[0]['nickname'] = 'Nombre de prueba'
        self.db['profiles'].rows.append({'username': 'Other', 'username_key': 'other', 'nickname': 'Otro'})
        self.service = stored_profiles.StoredProfiles(self.db)

    def test_profiles_expose_only_selector_fields(self):
        self.db['profiles'].rows[0]['private'] = 'not-public'
        result = self.service.profiles()
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['profiles'][0], {
            'username': 'TestUser', 'username_key': 'testuser', 'nickname': 'Nombre de prueba'})

    def test_two_profiles_never_mix_publications_embeddings_or_related(self):
        self.generator.generate('testuser')
        first = self.service.publications('@TESTUSER')
        second = self.service.publications('other')
        self.assertEqual(first['profile_id'], 'testuser')
        self.assertEqual(first['summary']['generated'], 2)
        self.assertEqual(len(first['related']), 1)
        self.assertEqual(second['profile_id'], 'other')
        self.assertEqual(second['summary']['generated'], 0)
        self.assertEqual(second['summary']['pending'], 1)
        self.assertEqual(second['related'], [])
        self.assertEqual([row['publication_id'] for row in second['publications']], ['other'])
        self.assertNotIn('other', [row['publication_id'] for row in first['publications']])
        self.assertEqual(first, self.service.publications('testuser'))

    def test_only_current_model_hash_valid_real_vectors_are_counted(self):
        self.generator.generate('testuser')
        self.db['publications'].rows[0]['description'] = 'New description'
        self.assertEqual(self.service.publications('testuser')['summary']['generated'], 1)
        self.db['embeddings'].rows[1]['model'] = 'old-model'
        self.assertEqual(self.service.publications('testuser')['summary']['generated'], 0)
        self.db['embeddings'].rows[1]['model'] = MODEL
        for vector in ([0.0] * 1536, [float('nan')] * 1536, [1.0]):
            self.db['embeddings'].rows[1]['vector'] = vector
            data = self.service.publications('testuser')
            self.assertEqual(data['summary']['generated'], 0)
            self.assertEqual(data['related'], [])

    def test_history_does_not_hide_current_embeddings_and_ranking_is_real(self):
        self.generator.generate('testuser')
        self.db['embeddings'].rows[1]['vector'] = [-1.0] + [0.0] * 1535
        for index in range(15):
            self.db['embeddings'].rows.append({**self.db['embeddings'].rows[0], 'content_hash': str(index)})
        result = self.service.publications('testuser')
        self.assertEqual(result['summary']['generated'], 2)
        self.assertEqual(result['related'][0]['similarity'], -1)
        self.assertNotIn('vector', str(result))

    def test_related_pairs_are_sorted_and_limited_to_five(self):
        db, client, factory, generator = fixture(5)
        generator.generate('testuser')
        db['embeddings'].rows[0]['vector'] = [-1.0] + [0.0] * 1535
        result = stored_profiles.StoredProfiles(db).publications('testuser')
        self.assertEqual(len(result['related']), 5)
        self.assertTrue(all(pair['similarity'] == 1 for pair in result['related']))
        self.assertTrue(all('100' not in (pair['first_publication_id'], pair['second_publication_id'])
                            for pair in result['related']))

    def test_empty_profiles_and_descriptions_and_generation_scope(self):
        self.db['publications'].rows[0]['description'] = '  '
        result = self.service.publications('testuser')
        self.assertEqual(result['summary'], {'available': 2, 'generated': 0, 'pending': 1,
            'empty': 1, 'generation_pending': 1, 'generation_limit': 10})
        self.db['publications'].rows.clear()
        result = self.service.publications('testuser')
        self.assertEqual(result['publications'], [])
        self.assertEqual(result['related'], [])
        db, _, _, _ = fixture(15)
        result = stored_profiles.StoredProfiles(db).publications('testuser')
        self.assertEqual(result['summary']['available'], 15)
        self.assertEqual(result['summary']['pending'], 15)
        self.assertEqual(result['summary']['generation_pending'], 10)

    def test_reads_do_not_write_or_create_clients(self):
        before = {name: deepcopy(collection.rows) for name, collection in self.db.items()}
        with patch('backend.embeddings.OpenAI') as sdk, patch.object(main, 'scrape_profile') as scrape:
            self.service.profiles()
            self.service.publications('testuser')
            sdk.assert_not_called()
            scrape.assert_not_called()
        self.assertEqual(before, {name: collection.rows for name, collection in self.db.items()})
        for collection in self.db.values():
            collection.create_index.assert_not_called()

    def test_unknown_profile(self):
        with self.assertRaises(LookupError):
            self.service.publications('missing')

    def test_read_routes_and_safe_errors_close_client(self):
        db = Mock()
        db.__getitem__ = Mock(side_effect=self.db.__getitem__)
        with patch.object(stored_profiles, 'get_database', return_value=db), \
                patch.object(main, 'scrape_profile', side_effect=AssertionError('No scraper')), \
                patch('backend.embeddings.OpenAI', side_effect=AssertionError('No OpenAI')):
            status, result = asyncio.run(request('GET', '/api/stored-profiles'))
            self.assertEqual((status, result['count']), (200, 2))
            status, result = asyncio.run(request('GET', '/api/stored-profiles/Other/publications'))
            self.assertEqual((status, result['profile_id']), (200, 'other'))
            status, _ = asyncio.run(request('GET', '/api/stored-profiles/missing/publications'))
            self.assertEqual(status, 404)
        self.assertEqual(db.client.close.call_count, 3)
        with patch.object(stored_profiles, 'get_database', side_effect=RuntimeError('secret-uri')):
            status, result = asyncio.run(request('GET', '/api/stored-profiles'))
            self.assertEqual(status, 503)
            self.assertNotIn('secret-uri', str(result))


if __name__ == '__main__':
    unittest.main()
