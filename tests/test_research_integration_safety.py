"""Isolation guards only; normal discovery never connects to real MongoDB."""
import unittest
from unittest.mock import Mock, patch

from integration_research_mongodb import Context


class MongoIntegrationSafetyTests(unittest.TestCase):
    def test_unsafe_endpoints_and_database_names_fail_before_connecting(self):
        good = 'mongodb://127.0.0.1:32768/?replicaSet=msIntegration&directConnection=true'
        for uri, database, replica in (
            ('mongodb://127.0.0.1:27017/?replicaSet=msIntegration&directConnection=true', 'media_scraper_integration_new', 'msIntegration'),
            ('mongodb://remote.example:32768/?replicaSet=msIntegration&directConnection=true', 'media_scraper_integration_new', 'msIntegration'),
            ('mongodb://user:password@127.0.0.1:32768/?replicaSet=msIntegration&directConnection=true', 'media_scraper_integration_new', 'msIntegration'),
            (good, 'media_scraper', 'msIntegration'), (good, 'admin', 'msIntegration'),
            (good, 'media_scraper_integration_new', 'productionReplica'),
            ('mongodb://127.0.0.1:32768/', 'media_scraper_integration_new', 'msIntegration'),
        ):
            with self.subTest(database=database, replica=replica), patch.object(Context, 'new_client') as connect:
                with self.assertRaises(RuntimeError):
                    Context(uri, database, replica)
                connect.assert_not_called()

    def test_preexisting_database_refused_without_writes(self):
        client = Mock()
        client.admin.command.return_value = {'setName': 'msIntegration', 'isWritablePrimary': True}
        client.list_database_names.return_value = ['media_scraper_integration_preexisting']
        with patch.object(Context, 'new_client', return_value=client):
            with self.assertRaisesRegex(RuntimeError, 'database already exists'):
                Context('mongodb://127.0.0.1:32768/?replicaSet=msIntegration&directConnection=true',
                        'media_scraper_integration_preexisting', 'msIntegration')
        client.close.assert_called_once()
        # Only hello/listDatabaseNames are permitted before the refusal.
        self.assertEqual(client.admin.command.call_args.args, ('hello',))

    def test_incompatible_replica_set_refused_before_any_database_creation(self):
        client = Mock()
        client.admin.command.return_value = {'setName': 'different', 'isWritablePrimary': True}
        with patch.object(Context, 'new_client', return_value=client):
            with self.assertRaisesRegex(RuntimeError, 'replica set'):
                Context('mongodb://127.0.0.1:32768/?replicaSet=msIntegration&directConnection=true',
                        'media_scraper_integration_new', 'msIntegration')
        client.list_database_names.assert_not_called()
        client.close.assert_called_once()
