from djangae.contrib.common import _thread_locals
from django.core.signals import request_finished


try:
    from django.utils.deprecation import MiddlewareMixin
except ImportError:
    MiddlewareMixin = object


def wipe_request(*args, **kwargs):
    _thread_locals.request = None


class RequestStorageMiddleware(MiddlewareMixin):
    """ Middleware which allows us to get hold of the request object in
        places where Django doesn't give it to us, e.g. in model save methods.
        Use get_request() to access the request object.
    """

    def __init__(self, *args, **kwargs):
        # Wipe the request when it's completed (process_response happens too early)
        # we set dispatch_uid so this will only connect once even if the middleware
        # is reconstructed
        request_finished.connect(
            wipe_request,
            dispatch_uid="request_storage_middleware"
        )

        super().__init__(*args, **kwargs)

    def process_request(self, request):
        _thread_locals.request = request
