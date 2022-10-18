import logging
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.urls import reverse

from . import (
    _DEFAULT_OFFLINE_SETTING,
    _stash_scopes,
)
from .models import OAuthUserSession

login_required = login_required

def _get_offline_from_settings():
    # Defaulting to offline=True since it's recommended by google for web server apps
    # See comment in https://developers.google.com/identity/protocols/oauth2/web-server#python_7
    # If set to false, we wouldn't always have refresh tokens available
    return getattr(settings, _DEFAULT_OFFLINE_SETTING, True)

def oauth_scopes_required(scopes, offline=None):
    """
        When applied to a view, this will trigger an oauth-redirect flow, ensuring that
        the user has granted access to the required scopes.

        If the user did not login via oauth, they will be forced to do so. If the user
        already granted access to all scopes, then this will be a no-op.

        Requested scopes are stored temporarily in the session, and are "popped" during
        the oauth flow. We store in the session, rather than using the querystring, to
        prevent a possible attack vector where additional (unexpected) scopes could be
        granted to a hijacked account.

        Passing offline=True, will ask for an offline access_type and so the
        response from Google will include a refresh_token. By default this is always true
        unless the GOOGLEAUTH_OAUTH_OFFLINE setting is set to False.
    """

    def func_wrapper(function):
        @wraps(function)
        def wrapper(request, *args, **kwargs):
            login_reverse = f"{reverse('googleauth_oauth2login')}?next={request.get_full_path()}"

            if offline is None:
                offline = _get_offline_from_settings()

            oauth_session = (
                OAuthUserSession.objects.filter(pk=request.user.google_oauth_id).first()
                if request.user.is_authenticated
                else None
            )

            if oauth_session:
                # If we have an oauth session but we are asking for more scopes
                # then send them through the auth process again
                additional_scopes = set(scopes)
                current_scopes = set(oauth_session.scopes)

                difference = additional_scopes - current_scopes
                if difference:
                    logging.debug(
                        "Additional scopes (%s) requested for user (%s). Initiating auth flow.",
                        difference, request.user
                    )
                    # scopes have been added, we should redirect to login flow with those scopes
                    all_scopes = current_scopes.union(additional_scopes)
                    _stash_scopes(request, all_scopes, offline)
                    return HttpResponseRedirect(login_reverse)
                return function(request, *args, **kwargs)
            else:
                _stash_scopes(request, scopes, offline)
                return HttpResponseRedirect(login_reverse)

        return wrapper
    return func_wrapper


def auth_middleware_exempt(view_func):
    """Decorator to mark a view function that is to be skipped by
    the AuthenticationMiddleware.process_view method.
    """
    view_func._auth_middleware_exempt = True
    return view_func
