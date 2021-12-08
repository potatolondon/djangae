from djangae.environment import is_production_environment
from djangae.tasks.environment import tasks_location
from django.utils.log import DEFAULT_LOGGING

FILE_CACHE_LOCATION = '/tmp/cache' if is_production_environment() else '.cache'

CACHES = {
    # We default to the filesystem cache, since it's quick and easy for simple app
    # For larger application you should consider Cloud Memory Store (which does not have a free tier)
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': FILE_CACHE_LOCATION,
    }
}

LOGGING = DEFAULT_LOGGING.copy()
LOGGING['loggers']['djangae'] = {'level': 'INFO'}

# If on a production service, enable the StackDriver logging so that
# request logs are correctly grouped.
if is_production_environment():
    LOGGING = DEFAULT_LOGGING.copy()
    LOGGING['handlers']['stackdriver'] = {'class': 'djangae.core.logging.DjangaeLoggingHandler', 'level': 'DEBUG'}
    LOGGING['handlers']['console']['class'] = 'djangae.core.logging.DjangaeLoggingHandler'
    LOGGING['handlers']['django.server']['class'] = 'djangae.core.logging.DjangaeLoggingHandler'
    LOGGING['root'] = {'handlers': ['stackdriver'], 'level': 'DEBUG'}


# Setting to * is OK, because GAE takes care of domain routing - setting it to anything
# else just causes unnecessary pain when something isn't accessible under a custom domain
ALLOWED_HOSTS = ("*",)


# We set this default because Cloud Datastore uses signed 64 bit integers for IDs
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Set a default CLOUD_TASKS_LOCATION variable based on the environment (if we can)
CLOUD_TASKS_LOCATION = tasks_location()


# Default Django middleware, with the addition of the RequestStorageMiddleware
# for logging purposes
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'djangae.common.middleware.RequestStorageMiddleware',
]