# Installation

## Quickstart

The easiest and quickest way to get a project up and running with Djangae is to use the
[Djangae Scaffold](https://gitlab.com/potato-oss/djangae/djangae-scaffold) template.
This gives you a skeleton project with all the necessary configuration to get running right away.


## Manual installation

To create a project manually, or to adapt an existing Django project to run with Djangae follow these steps:

1. Make sure you have [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed, and you've installed the Datastore Emulator component.
1. For local development, you'll want to pip install `gcloud-tasks-emulator` and `gcloud-storage-emulator` from PyPi.
1. Create a Django project, add app.yaml and main.py to the root. Make sure Django 3.2+ is in your project and importable.
1. Add a requirements.txt to the root of your project, add djangae to it and install in your environment
1. Add `'djangae'` to `INSTALLED_APPS`, and probably also `'djangae.tasks'`.  This must come before any `django` apps.
1. We also recommend that you:
    - Add `'djangae.contrib.security'` to `INSTALLED_APPS'`.
    - Add `'djangae.contrib.security.middleware.AppEngineSecurityMiddleware'` to `MIDDLEWARE_CLASSES`.
1. At the top of your `settings.py`, insert the following line to setup some default settings:

```python
from djangae.settings_base import *
```

In `app.yaml` add the following handlers:

```yml
runtime: python37

handlers:
# This configures Google App Engine to serve the files in the app's static
# directory.
- url: /static
  static_dir: static/

# This handler routes all requests not caught above to your main app. It is
# required when static routes are defined, but can be omitted (along with
# the entire handlers section) when there are no static files defined.
- url: /.*
  script: auto
```

Make your `manage.py` look something like this:

```python
#!/usr/bin/env python
import os
import sys

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myapp.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    from djangae.sandbox import start_emulators, stop_emulators

    try:
        # Start all emulators, persisting data if we're not testing
        start_emulators(persist_data="test" not in sys.argv)
        execute_from_command_line(sys.argv)
    finally:
        # Stop all emulators
        stop_emulators()
```

Use the Django WSGI handler in your `main.py`, something like

```python
from .wsgi import application
app = application
```

If you want to use the Google Cloud Datastore as your database backend, add the following to your `settings.py`:

```python
from djangae.environment import project_id

DATABASES = {
    'default': {
        'ENGINE': 'gcloudc.db.backends.datastore',
        'PROJECT': project_id(),
        'INDEXES_FILE': DATASTORE_INDEX_YAML,
    }
}
```

It is recommended that for improved security you add `djangae.contrib.security.middleware.AppEngineSecurityMiddleware` as the first of your middleware classes. This middleware patches a number of insecure parts of the Python and App Engine libraries and warns if your Django settings aren't as secure as they could be.

## Deployment

Deploying your application is the same as deploying any Google App Engine project.

## Cache Backend

By default, Djangae uses `FileBasedCache` storing data in `.cache/` in your local env and in `/tmp` when deployed to GAE. This provides an in-memory caching system (`/tmp` is an in-memory filesystem), which is not shared across instances. If you need cross-instances cache we recommend using [Memorystore for Redis](https://cloud.google.com/memorystore/docs/redis) with [django-redis-cache](https://django-redis-cache.readthedocs.io/en/latest/index.html). Make sure you configure [VPC](https://cloud.google.com/appengine/docs/standard/python3/connecting-vpc) for your project to allow access to the redis instance from your GAE standard environment app. Your configuration should look something like this:

```python
# ...
from djangae.settings_base import *

CACHES = {
    'default': {
        'BACKEND': 'redis_cache.RedisCache',
        'LOCATION': '10.237.7.251:6379',
    },
}
```

## System views

Djangae ships handlers for various system functions. To enable them include djangae.urls in your url patterns. E.g.

```
urlpatterns = [
    path('_ah/', include('djangae.urls')),
]
```

The `_ah/` path is important as the views handle the built-in App Engine requests to `/_ah/warmup`, `/_ah/start`, and `/_ah/stop`.

Additionally Djangae implements a view at `/_ah/clearsessions` to handle clearing expired Django sessions from the database. You should
configure cron to post to this URL (see [sessions.md](sessions.md))
