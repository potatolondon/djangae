import os
from typing import Optional

from djangae.utils import memoized

# No SDK imports allowed in module namespace because `./manage.py runserver`
# imports this before the SDK is added to sys.path. See bugs #899, #1055.


def application_id(default="e~example") -> str:
    # Fallback to example on local or if this is not specified in the
    # environment already
    result = os.environ.get("GAE_APPLICATION", default)
    return result


def is_production_environment() -> bool:
    return not is_development_environment()


def is_development_environment() -> bool:
    return 'GAE_ENV' not in os.environ or os.environ['GAE_ENV'] != 'standard'


def gae_service_name():
    return os.environ.get("GAE_SERVICE", "default")


def gae_version() -> Optional[str]:
    """Returns the current GAE version."""
    return os.environ.get('GAE_VERSION')


@memoized
def get_application_root() -> str:
    """Traverse the filesystem upwards and return the directory containing app.yaml"""
    from django.conf import settings  # Avoid circular

    path = os.path.dirname(os.path.abspath(__file__))
    app_yaml_path = os.environ.get('DJANGAE_APP_YAML_LOCATION', None)

    # If the DJANGAE_APP_YAML_LOCATION variable is setup, will try to locate
    # it from there.
    if (app_yaml_path is not None and
            os.path.exists(os.path.join(app_yaml_path, "app.yaml"))):
        return app_yaml_path

    # Failing that, iterates over the parent folders until it finds it,
    # failing when it gets to the root
    while True:
        if os.path.exists(os.path.join(path, "app.yaml")):
            return path
        else:
            parent = os.path.dirname(path)
            if parent == path:  # Filesystem root
                break
            else:
                path = parent

    # Use the Django base directory as a fallback. We search for app.yaml
    # first because that will be the "true" root of the GAE app
    return settings.BASE_DIR


def default_gcs_bucket_name() -> str:
    return "%s.appspot.com" % project_id()


def default_app_host() -> str:
    """Returns the default HOST for the application.
    Fallbacks to example.appspost.com on local
    """

    return "%s.appspot.com" % project_id()


def app_host() -> str:
    """Returns the default HOST for the application.
    Fallbacks to example-dot-example.appspost.com on local
    """
    version = gae_version() or 'example'
    return "{}-dot-{}".format(version, default_app_host())


def project_id(default="example") -> str:
    # Environment variable will exist on production servers
    # fallback to "example" locally if it doesn't exist
    return os.environ.get("GOOGLE_CLOUD_PROJECT", default)
