import re
import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.functional import SimpleLazyObject

from google.cloud import logging
from google.cloud.logging_v2.handlers.handlers import (
    CloudLoggingHandler,
    EXCLUDED_LOGGER_DEFAULTS,
)

from djangae.contrib.common import get_request


_client_store = threading.local()

_DJANGAE_MIDDLEWARE_NAME = "djangae.contrib.common.middleware.RequestStorageMiddleware"

_DJANGO_TRACEPARENT = "HTTP_TRACEPARENT"
_DJANGO_XCLOUD_TRACE_HEADER = "HTTP_X_CLOUD_TRACE_CONTEXT"


# This function is from google.cloud.logging but is a private method so we've moved
# it here for safety
def _parse_trace_parent(header):
    """Given a w3 traceparent header, extract the trace and span ids.
    For more information see https://www.w3.org/TR/trace-context/

    Args:
        header (str): the string extracted from the traceparent header
            example: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
    Returns:
        Tuple[Optional[dict], Optional[str], bool]:
            The trace_id, span_id and trace_sampled extracted from the header
            Each field will be None if header can't be parsed in expected format.
    """
    trace_id = span_id = None
    trace_sampled = False
    # see https://www.w3.org/TR/trace-context/ for W3C traceparent format
    if header:
        try:
            VERSION_PART = r"(?!ff)[a-f\d]{2}"
            TRACE_ID_PART = r"(?![0]{32})[a-f\d]{32}"
            PARENT_ID_PART = r"(?![0]{16})[a-f\d]{16}"
            FLAGS_PART = r"[a-f\d]{2}"
            regex = f"^\\s?({VERSION_PART})-({TRACE_ID_PART})-({PARENT_ID_PART})-({FLAGS_PART})(-.*)?\\s?$"
            match = re.match(regex, header)
            trace_id = match.group(2)
            span_id = match.group(3)
            # trace-flag component is an 8-bit bit field. Read as an int
            int_flag = int(match.group(4), 16)
            # trace sampled is set if the right-most bit in flag component is set
            trace_sampled = bool(int_flag & 1)
        except (IndexError, AttributeError):
            # could not parse header as expected. Return None
            pass
    return trace_id, span_id, trace_sampled


# This function is from google.cloud.logging but is a private method so we've moved
# it here for safety
def _parse_xcloud_trace(header):
    """Given an X_CLOUD_TRACE header, extract the trace and span ids.

    Args:
        header (str): the string extracted from the X_CLOUD_TRACE header
    Returns:
        Tuple[Optional[dict], Optional[str], bool]:
            The trace_id, span_id and trace_sampled extracted from the header
            Each field will be None if not found.
    """
    trace_id = span_id = None
    trace_sampled = False
    # see https://cloud.google.com/trace/docs/setup for X-Cloud-Trace_Context format
    if header:
        try:
            regex = r"([\w-]+)?(\/?([\w-]+))?(;?o=(\d))?"
            match = re.match(regex, header)
            trace_id = match.group(1)
            span_id = match.group(3)
            trace_sampled = match.group(5) == "1"
        except IndexError:
            pass
    return trace_id, span_id, trace_sampled


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

        if not getattr(_client_store, "client", None):
            _client_store.client = logging.Client()

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
        # W3C traceparent header
        header = request.META.get(_DJANGO_TRACEPARENT)
        trace_id, span_id, trace_sampled = _parse_trace_parent(header)
        if trace_id is None:
            # traceparent not found. look for xcloud_trace_context header
            header = request.META.get(_DJANGO_XCLOUD_TRACE_HEADER)
            trace_id, span_id, trace_sampled = _parse_xcloud_trace(header)

        return trace_id, span_id, trace_sampled

    def fetch_labels(self, request):
        """
            Return a dictionary of labels to add to the logging records.

            By default we log the user_id if the user isn't anonymous. Otherwise
            we log None.
        """

        from django.utils.translation import get_language  # Inline as logging could be imported early

        user = getattr(request, "user")

        # We can't evaluate a user here if it's not already been evaluated
        # or bad things happen (circular dependency stuff) so we log "???"
        # to indicate there is a user of some sort, but we can't get its ID
        if isinstance(user, SimpleLazyObject):
            user_id = "???"
        else:
            user_id = getattr(user, "pk", None)

        ret = {
            "user_id": user_id,
            "language_code": get_language()
        }

        return {k: str(v) for k, v in ret.items()}

    def emit(self, record):
        # Google Logging profiles a list of loggers to ignore
        # as they are internal. Ideally this would be configured
        # in the Django logging setup but that just makes it a hassle for
        # users.
        if record.name in EXCLUDED_LOGGER_DEFAULTS:
            return

        request = get_request()
        if request:
            trace_id, span_id, trace_sampled = self.fetch_trace_and_span(request)
            record.trace = trace_id
            record.span_id = span_id
            record.trace_sampled = trace_sampled
            record.labels = self.fetch_labels(request)
        return super().emit(record)
