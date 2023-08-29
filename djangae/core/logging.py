import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from google.cloud import logging
from google.cloud.logging_v2.handlers.handlers import (
    CloudLoggingHandler,
)

from djangae.contrib.common import get_request


_client_store = threading.local()

_DJANGAE_MIDDLEWARE_NAME = "djangae.contrib.common.middleware.RequestStorageMiddleware"
_DJANGO_XCLOUD_TRACE_HEADER = "HTTP_X_CLOUD_TRACE_CONTEXT"


class DjangaeLoggingHandler(CloudLoggingHandler):
    """
        This is a logging handler that can be added to your Django logging settings
        and automatically adds the correct trace and span to your logging records.

        It also adds useful Django related variables to the log record labels. Currently these
        are:

        - user_id - The primary key of request.user
        - language_code - The active language
    """

    def __init__(self, *args, **kwargs):
        global _client_store

        if _DJANGAE_MIDDLEWARE_NAME not in settings.MIDDLEWARE:
            raise ImproperlyConfigured(
                "You must install the %s middleware to use the DjangaeLoggingHandler" % _DJANGAE_MIDDLEWARE_NAME
            )

        _client_store.client = logging.Client()
        _client_store.client.setup_logging()

        kwargs.setdefault("client", _client_store.client)
        super().__init__(*args, **kwargs)

    def fetch_trace_and_span(self, request):
        """
            Cloud Logging identifies a request with a "trace id", and a particular
            service within that request witha "span id". The trace ID is provided to
            us in a request header. The span id can be whatever we choose, so we use
            the id() of the request which persists for the lifetime of the request.

            span_id needs some special formatting though:

            https://cloud.google.com/logging/docs/reference/v2/rest/v2/LogEntry#FIELDS.span_id
        """
        trace_id = request.META.get(_DJANGO_XCLOUD_TRACE_HEADER)
        span_id = str(id(request))[:8]  # First 8 bytes of the request id
        span_id = bytes(span_id, "ascii").hex()  # Convert to hex, 16 chars long
        return trace_id, span_id

    def fetch_labels(self, request):
        """
            Return a dictionary of labels to add to the logging records.

            By default we log the user_id if the user isn't anonymous. Otherwise
            we log None.
        """

        from django.utils.translation import get_language  # Inline as logging could be imported early

        return {
            "user_id": getattr(getattr(request, "user", None), "pk", None),
            "language_code": get_language()
        }

    def emit(self, record):
        request = get_request()
        if request:
            trace_id, span_id = self.fetch_trace_and_span(request)
            record._trace = trace_id
            record._span_id = span_id
            record._labels = self.fetch_labels(request)
        return super().emit(record)
