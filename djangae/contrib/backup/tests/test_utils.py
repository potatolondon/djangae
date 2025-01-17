from django.conf import settings
from djangae.contrib import sleuth
from djangae.test import TestCase
from djangae import environment
from ..utils import get_backup_setting, get_gcs_bucket


class GetDatastoreSettingTest(TestCase):

    def test_set_as_expected(self):
        with self.settings(DJANGAE_BACKUP_FOO=True):
            self.assertTrue(
                get_backup_setting('FOO')
            )

    def test_default(self):
        self.assertFalse(hasattr(settings, 'FOO'))
        self.assertEqual(
            get_backup_setting('FOO', required=False, default='bar'),
            'bar'
        )

    def test_not_required(self):
        """if a settings isnt required then return None"""
        self.assertFalse(hasattr(settings, 'FOO'))
        self.assertIsNone(
            get_backup_setting('FOO', required=False),
        )

    def test_required_when_settings_does_not_exist(self):
        with self.assertRaises(Exception):
            get_backup_setting('FOO')


class GetGcsBucketTest(TestCase):

    def test_custom_bucket_setting(self):
        with self.settings(DJANGAE_BACKUP_GCS_BUCKET='foo-bar-baz/qux'):
            result = get_gcs_bucket()

            self.assertEqual(result, 'foo-bar-baz/qux')

    def test_no_bucket_setting(self):
        with self.assertRaises(AttributeError):
            settings.DJANGAE_BACKUP_GCS_BUCKET

        result = get_gcs_bucket()

        self.assertEqual(result, 'example.appspot.com/djangae-backups')

    def test_no_bucket_setting_and_no_default_bucket(self):
        with self.assertRaises(AttributeError):
            settings.DJANGAE_BACKUP_GCS_BUCKET

        with sleuth.fake('djangae.environment.default_gcs_bucket_name', None):
            bucket = environment.default_gcs_bucket_name()

            self.assertIsNone(bucket)

            with self.assertRaisesRegex(Exception, 'DJANGAE_BACKUP_GCS_BUCKET'):
                get_gcs_bucket()
