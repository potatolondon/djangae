import datetime
import json
import logging
import os

from django import shortcuts
from django.conf import settings
from django.contrib import auth
from django.http import (
    HttpResponseBadRequest,
    HttpResponseRedirect,
)
from django.urls import reverse
from django.utils import timezone
from google.auth.transport import requests
from google.oauth2 import id_token
from oauthlib.oauth2.rfc6749.errors import MismatchingStateError
from requests_oauthlib import OAuth2Session

from djangae import environment

from . import (
    _CLIENT_ID_SETTING,
    _CLIENT_SECRET_SETTING,
    _DEFAULT_SCOPES_SETTING,
    _OAUTH_REDIRECT_HOST,
    _SKEW_SECONDS_SETTING,
    _pop_scopes,
)
from .backends.oauth2 import OAuthBackend
from .decorators import auth_middleware_exempt
from .models import OAuthUserSession

STATE_SESSION_KEY = 'oauth-state'
_DEFAULT_OAUTH_SCOPES = [
    "openid",
    "profile",
    "email"
]
AUTHORIZATION_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://www.googleapis.com/oauth2/v4/token"

GOOGLE_USER_INFO = "https://www.googleapis.com/oauth2/v1/userinfo"

# The time in seconds that we take away from the given
# expires_in value to account for delay from the server
# to the application. "expires_in" is relative to the time
# the token was granted, not the time we process it
_TOKEN_EXPIRATION_GUARD_TIME = 5


# The time in seconds that is used by `verify_oauth2_token` to compensate for differences
# in clocks between local time and server time. This used to be baked in google-auth but has
# been changed from being hardcoded to 10seconds to being a parameter that defaults to 0.
# We're reverting back to the default of 10 seconds here
_DEFAULT_CLOCK_SKEW_SECONDS = 10


def _get_clock_skew_seconds():
    return getattr(settings, _SKEW_SECONDS_SETTING, _DEFAULT_CLOCK_SKEW_SECONDS)


def _get_default_scopes():
    return getattr(settings, _DEFAULT_SCOPES_SETTING, _DEFAULT_OAUTH_SCOPES)


def _get_oauth_redirect_host_from_settings():
    return getattr(settings, _OAUTH_REDIRECT_HOST, None)

def _google_oauth2_session(request, additional_scopes=None, with_scope=True, **kwargs):
    scopes = _get_default_scopes()
    if additional_scopes:
        scopes = set(scopes).union(set(additional_scopes))

    if with_scope:
        kwargs['scope'] = sorted(scopes)

    hardcoded_redirect_host = _get_oauth_redirect_host_from_settings()

    # Use hardcoded uri for oauth flow to avoid having to set redirect_urls
    # for every single new app version.
    redirect_host = hardcoded_redirect_host if hardcoded_redirect_host is not None else request.META['HTTP_HOST']
    redirect_url = f"{request.scheme}://{redirect_host}"

    kwargs['redirect_uri'] = f"{redirect_url}{reverse('googleauth_oauth2callback')}"
    logging.info('Create google oauth2 session with redirect uri: %s', kwargs['redirect_uri'])

    client_id = getattr(settings, _CLIENT_ID_SETTING)
    assert client_id

    return OAuth2Session(client_id, **kwargs)


@auth_middleware_exempt
def oauth_login(request):
    """
        This view should be set as your login_url for using OAuth
        authentication. It will trigger the main oauth flow.
    """
    additional_scopes, offline = _pop_scopes(request)

    next_url = request.GET.get('next')

    if next_url:
        request.session[auth.REDIRECT_FIELD_NAME] = next_url

    google = _google_oauth2_session(request, additional_scopes=additional_scopes)

    oauth2_state = json.dumps({
        'token': google.new_state(),
        'hostname': request.META['HTTP_HOST'],
    })

    kwargs = {
        "state": oauth2_state,
        "prompt": "select_account",
        "include_granted_scopes": 'true'
    }

    oauth_session = (
        OAuthUserSession.objects.filter(pk=request.user.google_oauth_id).first()
        if request.user.is_authenticated
        else None
    )
    if oauth_session:
        being_requested = set(google.scope)
        current_scopes = set(oauth_session.scopes)

        difference = being_requested - current_scopes

        # Oauth session exists (it's ok if it expired, see #1292)...
        if not difference:
            # ...and we already have all the scopes, no need to prompt
            kwargs["prompt"] = "none"

    if offline:
        kwargs["access_type"] = "offline"

    authorization_url, state = google.authorization_url(
        AUTHORIZATION_BASE_URL,
        **kwargs
    )

    request.session[STATE_SESSION_KEY] = state

    return HttpResponseRedirect(authorization_url)


def _calc_expires_at(expires_in):
    """
        Given an expires_in seconds time from
        the Google OAuth2 authentication process,
        this returns an actual datetime of when
        the expiration is, relative to the current time.
        This uses a naive UTC datetime since it's what google.oauth2 uses
    """

    if not expires_in:
        # Already expired
        return datetime.datetime.utcnow()

    try:
        expires_in = int(expires_in)
    except (TypeError, ValueError):
        return datetime.datetime.utcnow()

    expires_in -= _TOKEN_EXPIRATION_GUARD_TIME
    return datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)


@auth_middleware_exempt
def oauth2callback(request):
    if environment.is_development_environment():
        # hack required for login to work when running the app locally;
        # the required env var `OAUTHLIB_INSECURE_TRANSPORT` cannot be set in the shell or
        # `manage.py` because dev_appserver ignores env vars not set in `app.yaml`'s
        # `env_variables` section;
        # see https://oauthlib.readthedocs.io/en/latest/oauth2/security.html#environment-variables
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    try:
        encoded_state = request.GET['state']
    except KeyError:
        msg = 'Missing state'
        logging.exception(msg)
        return HttpResponseBadRequest(msg)

    try:
        state = json.loads(encoded_state)
        original_hostname = state['hostname']
    except (ValueError, KeyError):
        msg = 'Invalid state'
        logging.exception(msg)
        return HttpResponseBadRequest(msg)

    # If we began the auth flow on a non-default version then (optionaly) redirect
    # back to the version we started on. This avoids having to add authorized
    # redirect URIs to the console for every deployed version.
    if _get_oauth_redirect_host_from_settings() and original_hostname != request.META['HTTP_HOST']:
        logging.debug('Redirect to version %s', original_hostname)
        return shortcuts.redirect(
            '{}://{}{}'.format(
                request.scheme,
                original_hostname,
                request.get_full_path()
            )
        )

    if STATE_SESSION_KEY not in request.session:
        logging.exception("Missing oauth state from session")
        return HttpResponseBadRequest()

    client_id = getattr(settings, _CLIENT_ID_SETTING)
    client_secret = getattr(settings, _CLIENT_SECRET_SETTING)

    assert client_id and client_secret

    google = _google_oauth2_session(request, with_scope=False, state=request.session[STATE_SESSION_KEY])

    # If we have a next_url, then on error we can redirect there
    # as that will likely restart the flow, if not, we'll raise
    # a bad request on error
    has_next_url = auth.REDIRECT_FIELD_NAME in request.session

    next_url = (
        request.session[auth.REDIRECT_FIELD_NAME]
        if has_next_url
        else settings.LOGIN_REDIRECT_URL
    )

    failed = False

    try:
        token = google.fetch_token(
            TOKEN_URL,
            client_secret=client_secret,
            authorization_response=request.build_absolute_uri()
        )
    except MismatchingStateError:
        logging.exception("Mismatched state error in oauth handling")
        failed = True

    if google.authorized:
        try:
            profile = id_token.verify_oauth2_token(
                token['id_token'],
                requests.Request(),
                client_id,
                clock_skew_in_seconds=_get_clock_skew_seconds()
            )
        except ValueError:
            logging.exception("Error verifying OAuth2 token")
            failed = True
        else:
            pk = profile["sub"]

            defaults = dict(
                access_token=token['access_token'],
                token_type=token['token_type'],
                expires_at=_calc_expires_at(token['expires_in']),
                profile=profile,
                scopes=token['scope']
            )

            # Refresh tokens only exist on the first authorization
            # or, if you've specified the access_type as "offline"
            if 'refresh_token' in token:
                defaults['refresh_token'] = token['refresh_token']

            session, _ = OAuthUserSession.objects.update_or_create(
                pk=pk,
                defaults=defaults
            )

            # credentials are valid, we should authenticate the user
            user = OAuthBackend().authenticate(request, oauth_session=session)
            if user:
                logging.debug("Successfully authenticated %s via OAuth2", user)

                user.backend = 'djangae.contrib.googleauth.backends.oauth2.%s' % OAuthBackend.__name__

                # If we successfully authenticate, then we need to logout
                # and back in again. This is because the user may have
                # authenticated with another backend, but we need to re-auth
                # with the OAuth backend
                if request.user.is_authenticated:
                    # We refresh as authenticate may have changed the user
                    # and if logout ever does a save we might lose that
                    request.user.refresh_from_db()
                    auth.logout(request)

                auth.login(request, user)
            else:
                failed = True
                logging.warning(
                    "Failed Django authentication after getting oauth credentials"
                )
    else:
        failed = True
        logging.warning(
            "Something failed during the OAuth authorization process for user: %s",
        )

    if failed and not has_next_url:
        return HttpResponseBadRequest()

    # We still redirect to the next_url, as this should trigger
    # the oauth flow again, if we didn't authenticate
    # successfully.
    return HttpResponseRedirect(next_url)
