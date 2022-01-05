# None of this is django-specific. Don't import from django.

import os
import sys
import contextlib
import subprocess
import getpass
import logging

from os.path import commonprefix

# try both the python 2 and 3 import to avoid six dependency or django import
try:
    from urllib import quote
except ImportError:
    from urllib.parse import quote

from . import environment
from .utils import get_next_available_port

_SCRIPT_NAME = 'dev_appserver.py'

_API_SERVER = None

# We use this list to prevent user using certain dev_appserver options that
# might collide with some Django settings.
WHITELISTED_DEV_APPSERVER_OPTIONS = [
    'A',
    'admin_host',
    'admin_port',
    'auth_domain',
    'storage_path',
    'log_level',
    'max_module_instances',
    'use_mtime_file_watcher',
    'appidentity_email_address',
    'appidentity_private_key_path',
    'blobstore_path',
    'datastore_path',
    'clear_datastore',
    'datastore_consistency_policy',
    'require_indexes',
    'auto_id_policy',
    'logs_path',
    'show_mail_body',
    'enable_sendmail',
    'prospective_search_path',
    'clear_prospective_search',
    'search_indexes_path',
    'clear_search_indexes',
    'enable_task_running',
    'allow_skipped_files',
    'api_port',
    'dev_appserver_log_level',
    'skip_sdk_update_check',
    'default_gcs_bucket_name',
]

DEFAULT_API_PORT = 8010
DEFAULT_ADMIN_PORT = 8011
DEFAULT_BLOBSTORE_SERVICE_PORT = 8012

# This is a temporary workaround for the issue with 1.9.49 version where
# version is set to [0, 0, 0] instead of [1, 9, 49]. This could be removed
# after this: https://code.google.com/p/googleappengine/issues/detail?id=13439
# issue is resolved. If that is done, we should remove all references to
# TEMP_1_9_49_VERSION_NO here and in djangae/management/command/runserver.
TEMP_1_9_49_VERSION_NO = [0, 0, 0]


class Filter(object):
    def filter(self, record):
        if record.funcName == '__StarSchemaQueryPlan' and record.module == 'datastore_sqlite_stub':
            return 0
        elif record.funcName == 'Run' and record.module == 'datastore':
            return 0
        else:
            return 1


def _disable_sqlite_stub_logging():
    """
        For some reason, Google decided to log all queries at debug level to the
        root logger when running stuff locally. This switches that off (if you want it, then just
        remove the filter)
    """
    logging.getLogger().addFilter(Filter())


def _find_sdk_from_python_path():
    import google.appengine
    # Make sure we get the path of the 'google' module which contains 'appengine', as it's possible
    # that there are several.
    return os.path.abspath(os.path.dirname(os.path.dirname(google.appengine.__path__[0])))


def _find_sdk_from_path():
    # Assumes `script_name` is on your PATH - SDK installers set this up
    which = 'where' if sys.platform == "win32" else 'which'
    path = subprocess.check_output([which, _SCRIPT_NAME]).strip()
    sdk_dir = os.path.dirname(os.path.realpath(path))

    if os.path.exists(os.path.join(sdk_dir, 'bootstrapping')):
        # Cloud SDK
        sdk_dir = os.path.abspath(os.path.join(sdk_dir, '..', 'platform', 'google_appengine'))
        if not os.path.exists(sdk_dir):
            raise RuntimeError(
                'The Cloud SDK is on the path, but the app engine SDK dir could not be found'
            )
        else:
            return sdk_dir
    else:
        # Regular App Engine SDK
        return sdk_dir


def _create_dispatcher(configuration, options):
    from google.appengine.tools.devappserver2 import dispatcher
    from google.appengine.tools.devappserver2.devappserver2 import DevelopmentServer

    from djangae.compat import _LOG_LEVEL_TO_RUNTIME_CONSTANT

    from google.appengine.tools.sdk_update_checker import GetVersionObject, \
                                                          _VersionList

    if hasattr(_create_dispatcher, "singleton"):
        return _create_dispatcher.singleton

    class UnsupportedOption(object):
        pass

    current_version = _VersionList(GetVersionObject()['release'])
    supports_go_config = current_version >= _VersionList('1.9.50')
    supports_custom_config = current_version >= _VersionList('1.9.22') or current_version == TEMP_1_9_49_VERSION_NO
    supports_external_port = current_version >= _VersionList('1.9.19') or current_version == TEMP_1_9_49_VERSION_NO
    supports_watcher_ignore_re = current_version >= _VersionList('1.9.54')

    dispatcher_args = [
        configuration,
        options.host,
        options.port,
        options.auth_domain,
        _LOG_LEVEL_TO_RUNTIME_CONSTANT[options.log_level],
        DevelopmentServer._create_php_config(options),
        DevelopmentServer._create_python_config(options),
        DevelopmentServer._create_java_config(options),
        DevelopmentServer._create_go_config(options) if supports_go_config else UnsupportedOption,
        None if supports_custom_config else UnsupportedOption,
        DevelopmentServer._create_cloud_sql_config(options),
        DevelopmentServer._create_vm_config(options),
        DevelopmentServer._create_module_to_setting(options.max_module_instances,
                                       configuration, '--max_module_instances'),
        options.use_mtime_file_watcher,
        None if supports_watcher_ignore_re else UnsupportedOption,
        options.automatic_restart,
        options.allow_skipped_files,
        DevelopmentServer._create_module_to_setting(options.threadsafe_override,
                                       configuration, '--threadsafe_override'),
        options.external_port if supports_external_port else UnsupportedOption
    ]

    dispatcher_args = [x for x in dispatcher_args if not x is UnsupportedOption]

    _create_dispatcher.singleton = dispatcher.Dispatcher(*dispatcher_args)

    return _create_dispatcher.singleton


@contextlib.contextmanager
def _local(devappserver2=None, configuration=None, options=None, wsgi_request_info=None, **kwargs):

    # If we use `_LocalRequestInfo`, deferred tasks don't seem to work,
    # but with the default `WSGIRequestInfo`, building the request url for
    # blobstore uploads fails. So we inherit from `WSGIRequestInfo` and copy
    # the `get_request_url` from `_LocalRequestInfo`
    class CustomWSGIRequestInfo(wsgi_request_info.WSGIRequestInfo):
        def get_request_url(self, request_id):
            """Returns the URL the request e.g. 'http://localhost:8080/foo?bar=baz'.

            Args:
              request_id: The string id of the request making the API call.

            Returns:
              The URL of the request as a string.
            """
            try:
                host = os.environ['HTTP_HOST']
            except KeyError:
                host = os.environ['SERVER_NAME']
                port = os.environ['SERVER_PORT']
                if port != '80':
                    host += ':' + port
            url = 'http://' + host
            url += quote(os.environ.get('PATH_INFO', '/'))
            if os.environ.get('QUERY_STRING'):
                url += '?' + os.environ['QUERY_STRING']
            return url

    global _API_SERVER

    _disable_sqlite_stub_logging()

    original_environ = os.environ.copy()

    # Silence warnings about this being unset, localhost:8080 is the dev_appserver default.
    # Note that we're setting things for the *Blobstore* handler in os.environ here, which seems
    # kind of crazy, and probably is, but it seems to be necessary to make stuff work.
    url = "localhost"
    port = get_next_available_port(url, DEFAULT_BLOBSTORE_SERVICE_PORT)
    os.environ.setdefault("HTTP_HOST", "{}:{}".format(url, port))
    os.environ['SERVER_NAME'] = url
    os.environ['SERVER_PORT'] = str(port)
    os.environ['DEFAULT_VERSION_HOSTNAME'] = '%s:%s' % (os.environ['SERVER_NAME'], os.environ['SERVER_PORT'])

    devappserver2._setup_environ(configuration.app_id)

    from google.appengine.tools.devappserver2 import api_server
    from google.appengine.tools.sdk_update_checker import GetVersionObject, _VersionList

    if hasattr(api_server, "get_storage_path"):
        storage_path = api_server.get_storage_path(options.storage_path, configuration.app_id)
    else:
        # SDK < 1.9.51
        storage_path = devappserver2._get_storage_path(options.storage_path, configuration.app_id)

    dispatcher = _create_dispatcher(configuration, options)
    request_data = CustomWSGIRequestInfo(dispatcher)
    # Remember the wsgi request info object so it can be reused to avoid duplication.
    dispatcher._request_data = request_data

    # We set the API and Admin ports so that they are beyond any modules (if you
    # have 10 modules then these values will shift, but it's better that they are predictable
    # in the common case)
    options.api_port = get_next_available_port(url, max(DEFAULT_API_PORT, port + 1))
    options.admin_port = get_next_available_port(url, max(DEFAULT_ADMIN_PORT, options.api_port + 1))

    if hasattr(api_server, "create_api_server"):
        current_version = _VersionList(GetVersionObject()['release'])
        app_rather_than_config = current_version >= _VersionList('1.9.54')

        # Google changed the argument structure in version 1.9.54 so we have to
        # conditionally supply the args here
        if app_rather_than_config:
            _API_SERVER = api_server.create_api_server(
                request_data,
                storage_path,
                options,
                configuration.app_id,
                environment.get_application_root()
            )
        else:
            _API_SERVER = api_server.create_api_server(
                request_data, storage_path, options, configuration
            )

        # We have to patch api_server.create_api_server to return _API_SERVER
        # every time it's called, without this we end up with all kinds of
        # problems. Basically we need one api server for the lifetime of the
        # sandbox (including in `runserver`)
        def create_api_server_patch(*args, **kwargs):
            return _API_SERVER

        api_server.create_api_server = create_api_server_patch

    else:

        _API_SERVER = devappserver2.DevelopmentServer._create_api_server(
            request_data, storage_path, options, configuration
        )

    from .blobstore_service import start_blobstore_service, stop_blobstore_service

    start_blobstore_service()
    try:
        yield
    finally:
        api_server.cleanup_stubs()
        os.environ = original_environ
        stop_blobstore_service()


@contextlib.contextmanager
def _remote(configuration=None, remote_api_stub=None, apiproxy_stub_map=None, **kwargs):

    def auth_func():
        return raw_input('Google Account Login: '), getpass.getpass('Password: ')

    original_apiproxy = apiproxy_stub_map.apiproxy

    if configuration.app_id.startswith('dev~'):
        app_id = configuration.app_id[4:]
    else:
        app_id = configuration.app_id

    os.environ['HTTP_HOST'] = '{0}.appspot.com'.format(app_id)
    os.environ['DEFAULT_VERSION_HOSTNAME'] = os.environ['HTTP_HOST']

    try:
        from google.appengine.tools.appcfg import APPCFG_CLIENT_ID, APPCFG_CLIENT_NOTSOSECRET
        from google.appengine.tools import appengine_rpc_httplib2

        params = appengine_rpc_httplib2.HttpRpcServerOAuth2.OAuth2Parameters(
            access_token=None,
            client_id=APPCFG_CLIENT_ID,
            client_secret=APPCFG_CLIENT_NOTSOSECRET,
            scope=remote_api_stub._OAUTH_SCOPES,
            refresh_token=None,
            credential_file=os.path.expanduser("~/.djangae_oauth2_tokens"),
            token_uri=None
        )

        def factory(*args, **kwargs):
            kwargs["auth_tries"] = 3
            return appengine_rpc_httplib2.HttpRpcServerOAuth2(*args, **kwargs)

        remote_api_stub.ConfigureRemoteApi(
            app_id=None,
            path='/_ah/remote_api',
            auth_func=params,
            servername='{0}.appspot.com'.format(app_id),
            secure=True,
            save_cookies=True,
            rpc_server_factory=factory
        )
    except ImportError:
        logging.exception("Unable to use oauth2 falling back to username/password")
        remote_api_stub.ConfigureRemoteApi(
            None,
            '/_ah/remote_api',
            auth_func,
            servername='{0}.appspot.com'.format(app_id),
            secure=True,
        )

    ps1 = getattr(sys, 'ps1', None)
    red = "\033[0;31m"
    native = "\033[m"
    sys.ps1 = red + '(remote) ' + app_id + native + ' >>> '

    try:
        yield
    finally:
        apiproxy_stub_map.apiproxy = original_apiproxy
        sys.ps1 = ps1


@contextlib.contextmanager
def _test(**kwargs):
    """
        This stub uses the testbed to initialize the bare minimum to use the
        Datastore connector. Tests themselves should setup/tear down their own
        stubs by using DjangaeDiscoverRunner or the nose plugin.

        The stubs here are just for bootstrapping the tests. Obviously any data inserted
        between here, and the tests themselves will be wiped out when the tests begin!
    """

    from google.appengine.ext import testbed
    from google.appengine.datastore import datastore_stub_util

    MINIMAL_STUBS = {
        "init_app_identity_stub": {},
        "init_memcache_stub": {},
        "init_datastore_v3_stub": {
            "use_sqlite": True,
            "auto_id_policy": testbed.AUTO_ID_POLICY_SCATTERED,
            "consistency_policy": datastore_stub_util.PseudoRandomHRConsistencyPolicy(probability=1)
        }
    }

    from .blobstore_service import start_blobstore_service, stop_blobstore_service

    # Dummy values for testing, based on the defaults for dev_appserver
    # (differentiating between the default runserver port of 8000 can also be useful
    # for picking up hard-coding issues etc.)
    os.environ["HTTP_HOST"] = "localhost:8080"
    os.environ['SERVER_NAME'] = "localhost"
    os.environ['SERVER_PORT'] = "8080"

    os.environ['DEFAULT_VERSION_HOSTNAME'] = '%s:%s' % (
        os.environ['SERVER_NAME'], os.environ['SERVER_PORT']
    )

    testbed = testbed.Testbed()
    testbed.activate()
    for init_name, stub_kwargs in MINIMAL_STUBS.items():
        getattr(testbed, init_name)(**stub_kwargs)

    start_blobstore_service()
    try:
        yield
    finally:
        stop_blobstore_service()
        if testbed:
            testbed.deactivate()


LOCAL = 'local'
REMOTE = 'remote'
TEST = 'test'
SANDBOXES = {
    LOCAL: _local,
    REMOTE: _remote,
    TEST: _test,
}

_OPTIONS = None
_CONFIG = None

@contextlib.contextmanager
def activate(sandbox_name, add_sdk_to_path=False, new_env_vars=None, **overrides):
    """Context manager for command-line scripts started outside of dev_appserver.

    :param sandbox_name: str, one of 'local', 'remote' or 'test'
    :param add_sdk_to_path: bool, optionally adds the App Engine SDK to sys.path
    :param options_override: an options structure to pass down to dev_appserver setup

    Available sandboxes:

      local: Adds libraries specified in app.yaml to the path and initializes local service stubs as though
             dev_appserver were running.

      remote: Adds libraries specified in app.yaml to the path and initializes remote service stubs.

      test: Adds libraries specified in app.yaml to the path and sets up no service stubs. Use this
            with `google.appengine.ext.testbed` to provide isolation for tests.

    Example usage:

        import djangae.sandbox as sandbox

        with sandbox.activate('local'):
            from django.core.management import execute_from_command_line
            execute_from_command_line(sys.argv)

    """
    if sandbox_name not in SANDBOXES:
        raise RuntimeError('Unknown sandbox "{}"'.format(sandbox_name))

    project_root = environment.get_application_root()

   # Store our original sys.path before we do anything, this must be tacked
    # onto the end of the other paths so we can access globally installed things (e.g. ipdb etc.)
    original_path = sys.path[:]

    # Setup paths as though we were running dev_appserver. This is similar to
    # what the App Engine script wrappers do.
    if add_sdk_to_path:
        try:
            import wrapper_util  # Already on sys.path
        except ImportError:
            sys.path[0:0] = [_find_sdk_from_path()]
            import wrapper_util
    else:
        try:
            import wrapper_util
        except ImportError:
            raise RuntimeError("Couldn't find a recent enough Google App Engine SDK, make sure you are using at least 1.9.6")

    sdk_path = _find_sdk_from_python_path()
    _PATHS = wrapper_util.Paths(sdk_path)

    project_paths = [] # Paths under the application root
    system_paths = [] # All other paths
    app_root = environment.get_application_root()

    # We need to look at the original path, and make sure that any paths
    # which are under the project root are first, then any other paths
    # are added after the SDK ones
    for path in _PATHS.scrub_path(_SCRIPT_NAME, original_path):
        if commonprefix([app_root, path]) == app_root:
            project_paths.append(path)
        else:
            system_paths.append(path)

    # We build a list of SDK paths, and add any additional ones required for
    # the oauth client
    appengine_paths = _PATHS.script_paths(_SCRIPT_NAME)
    for path in _PATHS.oauth_client_extra_paths:
        if path not in appengine_paths:
            appengine_paths.append(path)

    # Now, we make sure that paths within the project take precedence, followed
    # by the SDK, then finally any paths from the system Python (for stuff like
    # ipdb etc.)
    sys.path = (
        project_paths +
        appengine_paths +
        system_paths
    )

    # Gotta set the runtime properly otherwise it changes appengine imports, like wepapp
    # when you are not running dev_appserver
    import yaml
    with open(os.path.join(project_root, 'app.yaml'), 'r') as app_yaml:
        app_yaml = yaml.safe_load(app_yaml)
        os.environ['APPENGINE_RUNTIME'] = app_yaml.get('runtime', '')

    # Initialize as though `dev_appserver.py` is about to run our app, using all the
    # configuration provided in app.yaml.
    import google.appengine.tools.devappserver2.application_configuration as application_configuration
    import google.appengine.tools.devappserver2.devappserver2 as devappserver2
    import google.appengine.tools.devappserver2.wsgi_request_info as wsgi_request_info
    import google.appengine.ext.remote_api.remote_api_stub as remote_api_stub
    import google.appengine.api.apiproxy_stub_map as apiproxy_stub_map
    from djangae.compat import sandbox

    gae_args = [
        s for s in sys.argv
        if any(s.lstrip('--').startswith(gae_option) for gae_option in WHITELISTED_DEV_APPSERVER_OPTIONS)
    ]

    # The argparser is the easiest way to get the default options.
    options = devappserver2.PARSER.parse_args([project_root] + gae_args)
    options.enable_task_running = False # Disable task running by default, it won't work without a running server
    options.skip_sdk_update_check = True

    for option in overrides:
        if not hasattr(options, option):
            raise ValueError("Unrecognized sandbox option: {}".format(option))

        setattr(options, option, overrides[option])

    configuration = application_configuration.ApplicationConfiguration(options.config_paths, app_id=options.app_id)

    # Enable built-in libraries from app.yaml without enabling the full sandbox.
    module = configuration.modules[0]
    for l in sandbox._enable_libraries(module.normalized_libraries):
        sys.path.insert(1, l)

    # Propagate provided environment variables to the sandbox.
    # This is required for the runserver management command settings flag,
    # which sets an environment variable needed by Django.
    from google.appengine.api.appinfo import EnvironmentVariables
    old_env_vars = module.env_variables if module.env_variables else {}
    if new_env_vars is None:
        new_env_vars = {}
    module._app_info_external.env_variables = EnvironmentVariables.Merge(
        old_env_vars,
        new_env_vars,
    )

    try:
        global _OPTIONS
        global _CONFIG
        _CONFIG = configuration
        _OPTIONS = options # Store the options globally so they can be accessed later
        kwargs = dict(
            devappserver2=devappserver2,
            configuration=configuration,
            options=options,
            wsgi_request_info=wsgi_request_info,
            remote_api_stub=remote_api_stub,
            apiproxy_stub_map=apiproxy_stub_map,
        )
        with SANDBOXES[sandbox_name](**kwargs):
            yield

    finally:
        sys.path = original_path

@contextlib.contextmanager
def allow_mode_write():
    from google.appengine.tools.devappserver2.python import stubs

    original_modes = stubs.FakeFile.ALLOWED_MODES
    new_modes = set(stubs.FakeFile.ALLOWED_MODES)
    new_modes.add('w')
    new_modes.add('wb')

    original_dirs = stubs.FakeFile._allowed_dirs
    new_dirs = set(stubs.FakeFile._allowed_dirs or [])

    # for some reason when we call gettempdir in some scenarios
    # (we experience that in ajax call when we tried to render template
    # with assets) we might end up with thread.error when Python tries
    # to release the lock. Since we mess with the tempfile in allow_modules
    # we could - instead of calling gettempdir - simply add default temp
    # directories.
    new_dirs.update(['/tmp', '/var/tmp', '/usr/tmp'])

    stubs.FakeFile.ALLOWED_MODES = frozenset(new_modes)
    stubs.FakeFile._allowed_dirs = frozenset(new_dirs)
    try:
        yield
    finally:
        stubs.FakeFile.ALLOWED_MODES = original_modes
        stubs.FakeFile._allowed_dirs = original_dirs


class allow_modules_context():

    def __enter__(self):
        import sys
        import subprocess
        import os
        import tempfile
        import select
        # Clear the meta_path so google does not screw our imports, make a copy
        # of the old one
        self.old_meta_path = sys.meta_path
        sys.meta_path = []
        self.patch_modules = [os, tempfile, select, subprocess]

        import copy
        self.environ = copy.copy(os.environ)

        for mod in self.patch_modules:
            _system = reload(mod)
            mod.__dict__.update(_system.__dict__)

        # We have to maintain the environment, or bad things happen
        os.environ = self.environ # This gets monkey patched by GAE

    def __exit__(self, *exc):
        # Restore the original path
        sys.meta_path = self.old_meta_path
        # Reload the original modules
        for mod in self.patch_modules:
            _system = reload(mod)
            mod.__dict__.update(_system.__dict__)
        # Put the original os back, again
        os.environ = self.environ


def allow_modules(func, *args):
    """
        dev_appserver likes to kill your imports with meta_path madness so you
        use the internal ones instead of system ones, this wrapper reloads the
        modules and patches the google internal ones with the __dict__ from the
        system modules, this seems to be the cleanest way to do this even though
        it is a bit hacky
    """
    def _wrapped(*args, **kwargs):
        with allow_modules_context():
            return func(*args, **kwargs)
    return _wrapped
