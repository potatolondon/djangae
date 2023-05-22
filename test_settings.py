import logging
import os

from django.urls import (
    include,
    path,
)

BASE_DIR = os.path.dirname(__file__)
STATIC_URL = "/static/"

TEST_RUNNER = "djangae.test.AppEngineDiscoverRunner"

# Set the cache during tests to local memory, which is threadsafe
# then our TestCase clears the cache in setUp()
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
    },
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'djangae.contrib.common.middleware.RequestStorageMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'djangae.contrib.googleauth.middleware.AuthenticationMiddleware',
    'djangae.tasks.middleware.task_environment_middleware',
]

INSTALLED_APPS = (
    'djangae',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.auth',
    'djangae.contrib.googleauth',
    'gcloudc',
    'djangae.tasks',
    'djangae.contrib.search',
)

AUTHENTICATION_BACKENDS = [
    'djangae.contrib.googleauth.backends.iap.IAPBackend',
    'djangae.contrib.googleauth.backends.oauth2.OAuthBackend',
]

AUTH_USER_MODEL = "googleauth.User"

GOOGLEAUTH_CLIENT_ID = "test"
GOOGLEAUTH_CLIENT_SECRET = "test"

DATABASES = {
    'default': {
        'ENGINE': 'gcloudc.db.backends.datastore',
        'INDEXES_FILE': os.path.join(os.path.abspath(os.path.dirname(__file__)), "djangaeidx.yaml"),
        "PROJECT": "test",
        "NAMESPACE": "ns1",  # Use a non-default namespace to catch edge cases where we forget
        "OPTIONS": {
            "BULK_BATCH_SIZE": 25
        }
    }
}

SECRET_KEY = "secret_key_for_testing"

USE_TZ = True

CSRF_USE_SESSIONS = True

CLOUD_TASKS_LOCATION = "[LOCATION]"

# Define two required task queues
CLOUD_TASKS_QUEUES = [
    {
        "name": "default"
    },
    {
        "name": "another"
    }
]

NUM_PROXIES = 1

# Point the URL conf at this file
ROOT_URLCONF = __name__

urlpatterns = [
    path('tasks/', include('djangae.tasks.urls')),
    path('_ah/', include('djangae.urls')),
]

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# We set this default because Cloud Datastore uses signed 64 bit integers for IDs
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

logging.disable(logging.ERROR)
