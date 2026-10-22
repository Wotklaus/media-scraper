"""Synthetic normalization tests; no browser, credentials or database access."""
from copy import deepcopy
from datetime import datetime
import json
import unittest

from backend.normalizer import normalize_number, normalize_profile


def fixture():
    return {
        'username': 'example', 'nickname': 'Ejemplo ñ 🎵', 'followers': '18.6K',
        'following': '15', 'likes': '61.3K', 'followers_users': ['reader'],
        'videos': [
            {'id': '9876543210123456789', 'type': 'video', 'title': 'Descripción',
             'views': '1.0K', 'likes': '25', 'comments': '37', 'shares': '0',
             'saves': 'N/A', 'comments_list': [
                 {'cid': 9876543210123456799, 'username': 'reader', 'text': 'Hola ñ 🎵',
                  'digg_count': 2, 'create_time': 1700000000, 'reply_comment_total': 1,
                  'comment_language': 'es', 'cookies': 'synthetic-private-field'},
                 {'username': 'other', 'text': 'Sin ID en DOM'},
             ]},
            {'id': 9876543210123456788, 'type': 'photo', 'comments': '1.0K', 'comments_list': []},
        ],
        '_meta': {'mode': 'real', 'warnings': ['No se confirmó carga de comentarios.'],
                  'captured_at': '2026-10-22T00:00:00+00:00'},
        'cookies': 'synthetic-private-field',
    }


class NumberTests(unittest.TestCase):
    def test_suffixes_decimal_comma_whitespace_and_numeric_input(self):
        for value, expected in [('18.6K', 18600), ('61.3K', 61300), ('1.0K', 1000),
                                (' 2,5 k ', 2500), ('1.25M', 1250000), ('2B', 2000000000),
                                ('0', 0), (0, 0), (12.9, 12), ('123', 123)]:
            with self.subTest(value=value):
                self.assertEqual(normalize_number(value), expected)

    def test_invalid_nonfinite_negative_and_missing_values(self):
        for value in [None, True, False, 'N/A', '', 'text', {}, [], -1, '-1K',
                      float('nan'), float('inf'), float('-inf')]:
            with self.subTest(value=repr(value)):
                self.assertEqual(normalize_number(value), 0)


class ProfileTests(unittest.TestCase):
    def test_separate_documents_ids_relationships_and_metrics(self):
        result = normalize_profile(fixture())
        self.assertEqual(set(result), {'profile', 'publications', 'comments', 'extraction_metadata'})
        self.assertEqual(result['profile']['metrics'], {'followers': 18600, 'following': 15, 'likes': 61300})
        publication = result['publications'][0]
        self.assertEqual(publication['metrics']['views'], 1000)
        self.assertEqual(publication['metrics']['comments_count'], 37)
        self.assertEqual(publication['retrieved_comments_count'], 2)
        self.assertEqual(publication['comments_status'], 'recovered')
        self.assertIsNone(publication['comments_complete'])
        self.assertIsNone(publication['metrics']['saves'])
        self.assertEqual(result['publications'][1]['publication_id'], '9876543210123456788')
        comment = result['comments'][0]
        self.assertEqual(comment['comment_id'], '9876543210123456799')
        self.assertEqual(comment['publication_id'], publication['publication_id'])
        self.assertEqual(comment['profile_username'], 'example')
        self.assertEqual(comment['text'], 'Hola ñ 🎵')
        self.assertEqual(comment['reply_comment_total'], 1)
        self.assertEqual(comment['create_time'], 1700000000)
        self.assertIsNone(result['comments'][1]['comment_id'])
        self.assertEqual(result['extraction_metadata']['retrieved_comments_count'], 2)
        self.assertEqual(result['extraction_metadata']['publications_count'], 2)
        self.assertEqual(result['extraction_metadata']['publications_with_retrieved_comments'], 1)
        json.dumps(result, allow_nan=False)

    def test_empty_missing_or_null_comments_do_not_establish_absence(self):
        for count in ('0', '37', 'N/A', None):
            for comment_fields in ({}, {'comments_list': None}, {'comments_list': []}):
                with self.subTest(count=count, fields=comment_fields):
                    result = normalize_profile({'username': 'example', 'videos': [
                        {'id': '00123', 'comments': count, **comment_fields}]})
                    item = result['publications'][0]
                    self.assertEqual(item['publication_id'], '00123')
                    self.assertEqual(item['comments_status'], 'not_recovered')
                    self.assertIsNone(item['comments_complete'])
                    self.assertEqual(item['retrieved_comments_count'], 0)
                    self.assertEqual(result['comments'], [])
                    self.assertEqual(item['metrics']['comments_count'], normalize_number(count) if count in ('0', '37') else None)

    def test_metadata_preserved_and_input_not_mutated_or_aliased(self):
        original = fixture()
        before = deepcopy(original)
        result = normalize_profile(original)
        self.assertEqual(original, before)
        meta = result['extraction_metadata']
        self.assertEqual(meta['warnings'], original['_meta']['warnings'])
        self.assertEqual(meta['captured_at'], original['_meta']['captured_at'])
        self.assertIsNotNone(datetime.fromisoformat(meta['normalized_at']).tzinfo)
        meta['warnings'].append('Changed output')
        result['profile']['followers_users'].append('new_reader')
        self.assertEqual(original, before)
        self.assertNotIn('synthetic-private-field', json.dumps(result))

    def test_partial_profile_and_optional_profile_ids(self):
        result = normalize_profile({'username': 'example', 'id': 1234567890123456789, 'secUid': 'opaque-id'})
        self.assertEqual(result['profile']['id'], '1234567890123456789')
        self.assertEqual(result['profile']['secUid'], 'opaque-id')
        self.assertIsNone(result['profile']['metrics']['followers'])
        self.assertEqual(result['publications'], [])
        self.assertEqual(result['comments'], [])

    def test_invalid_input_fails_explicitly_without_inventing_ids(self):
        for profile in [None, {}, {'username': ' '}, {'username': 'x', 'videos': 'invalid'},
                        {'username': 'x', 'videos': [{}]},
                        {'username': 'x', 'videos': [{'id': True}]},
                        {'username': 'x', 'videos': [{'id': 1.5}]},
                        {'username': 'x', 'videos': [{'id': '1', 'comments_list': {}}]},
                        {'username': 'x', 'videos': [{'id': '1', 'comments_list': [{}]}]}]:
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                normalize_profile(profile)


if __name__ == '__main__':
    unittest.main()
