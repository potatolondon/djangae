import os
import tempfile

import yaml

from djangae import checks
from djangae.contrib import sleuth
from djangae.environment import get_application_root
from djangae.test import TestCase
from django.test.utils import override_settings


class ChecksTestCase(TestCase):
    def test_deferred_builtin_on(self):
        # Read and parse app.yaml
        app_yaml_path = os.path.join(get_application_root(), "app.yaml")
        with open(app_yaml_path, 'r') as f:
            app_yaml = yaml.safe_load(f.read())
        builtins = app_yaml.get('builtins', [])

        # Switch on deferred builtin
        builtins.append({'deferred': 'on'})
        app_yaml['builtins'] = builtins

        # Write to temporary app.yaml
        temp_app_yaml_dir = tempfile.mkdtemp()
        temp_app_yaml_path = os.path.join(temp_app_yaml_dir, "app.yaml")
        temp_app_yaml = file(temp_app_yaml_path, 'w')
        yaml.dump(app_yaml, temp_app_yaml)

        with sleuth.switch('djangae.checks.get_application_root', lambda : temp_app_yaml_dir) as mock_app_root:
            warnings = checks.check_deferred_builtin()
            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0].id, 'djangae.W001')

    def test_deferred_builtin_off(self):
        warnings = checks.check_deferred_builtin()
        self.assertEqual(len(warnings), 0)

    def test_csrf_check(self):
        errors = checks.check_session_csrf_enabled()
        self.assertEqual(len(errors), 0)

        with override_settings(MIDDLEWARE=[], MIDDLEWARE_CLASSES=[]):
            errors = checks.check_session_csrf_enabled()
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, 'djangae.E001')

    def test_csp_report_check(self):
        errors = checks.check_csp_is_not_report_only()
        self.assertEqual(len(errors), 0)

        with override_settings(CSP_REPORT_ONLY=True):
            errors = checks.check_csp_is_not_report_only()
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, 'djangae.E002')

    def test_csp_unsafe_check(self):
        errors = checks.check_csp_sources_not_unsafe()
        self.assertEqual(len(errors), 0)

        csp_settings = {k: ["'unsafe-inline'"] for k in checks.CSP_SOURCE_NAMES}
        with override_settings(**csp_settings):
            errors = checks.check_csp_sources_not_unsafe()
            self.assertEqual(len(errors), 9)

            # this assumes that errors come through in the same order as
            # checks.CSP_SOURCE_NAMES
            for idx, err in enumerate(errors):
                self.assertEqual(err.id, 'djangae.E1%02d' % idx)

    def test_template_loader_present(self):
        template_setting = [{
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'OPTIONS': {'loaders': [
                ('django.template.loaders.cached.Loader', ('django.template.loaders.filesystem.Loader',)),
            ]},
        }]
        with override_settings(TEMPLATES=template_setting):
            errors = checks.check_cached_template_loader_used()
            self.assertEqual(len(errors), 0)

    def test_template_loader_missing(self):
        template_setting = [{
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'OPTIONS': {'loaders': [('django.template.loaders.filesystem.Loader',)]},
        }]
        with override_settings(TEMPLATES=template_setting):
            errors = checks.check_cached_template_loader_used()
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, 'djangae.E003')

    def test_template_loader_skips_non_django_backends(self):
        template_setting = [{
            'BACKEND': 'nondjango.templates',
            'OPTIONS': {'loaders': [('nondjango.templates.Loader',)]},
        }]
        with override_settings(TEMPLATES=template_setting):
            errors = checks.check_cached_template_loader_used()
            self.assertEqual(len(errors), 0)

    def test_app_engine_sdk_version_check_supported(self):
        with sleuth.switch('djangae.checks._VersionList', lambda x: [1, 0, 0]):
            errors = checks.check_app_engine_sdk_version()
            self.assertEqual(len(errors), 0)

    def test_app_engine_sdk_version_check_unsupported(self):
        with sleuth.switch('djangae.checks._VersionList', lambda x: [100, 0, 0]):
            errors = checks.check_app_engine_sdk_version()
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, 'djangae.W002')
