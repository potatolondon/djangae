import hashlib
import logging
import os

from django import forms
from django.conf import settings
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    REDIRECT_FIELD_NAME,
    SESSION_KEY,
    _get_user_session_key,
    constant_time_compare,
    get_backends,
    get_user_model,
    load_backend,
    login,
    logout,
)
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.http import HttpResponseRedirect
from django.shortcuts import (
    redirect,
    render,
)
from django.urls.base import reverse
from django.utils.functional import SimpleLazyObject
from django.utils.http import urlencode

try:
    from gcloudc.db.backends.datastore.transaction import TransactionFailedError as DatabaseError
except ImportError:
    from django.db import DatabaseError

from djangae.contrib.googleauth import (
    _GOOG_AUTHENTICATED_USER_EMAIL_HEADER,
    _GOOG_AUTHENTICATED_USER_ID_HEADER,
    _GOOG_JWT_ASSERTION_HEADER,
)
from djangae.environment import is_production_environment
from djangae.utils import (
    retry,
    retry_on_error,
)

from .backends.iap import IAPBackend
from .backends.oauth2 import OAuthBackend
from .models import OAuthUserSession

_OAUTH_LINK_EXPIRY_SETTING = "GOOGLEAUTH_LINK_OAUTH_SESSION_EXPIRY"

logger = logging.getLogger(__name__)


def get_user_object(request):
    """
    Return the user model instance associated with the given request session.
    If no user is retrieved, return an instance of `AnonymousUser`.
    """
    from .models import AnonymousUser

    user = None
    try:
        user_id = _get_user_session_key(request)
        backend_path = request.session[BACKEND_SESSION_KEY]
    except KeyError:
        pass
    else:
        if backend_path in settings.AUTHENTICATION_BACKENDS:
            backend = load_backend(backend_path)
            user = backend.get_user(user_id)
            # Verify the session
            if hasattr(user, 'get_session_auth_hash'):
                session_hash = request.session.get(HASH_SESSION_KEY)
                session_hash_verified = session_hash and constant_time_compare(
                    session_hash,
                    user.get_session_auth_hash()
                )
                if not session_hash_verified:
                    request.session.flush()
                    user = None

    return user or AnonymousUser()


def get_user(request):
    if not hasattr(request, '_cached_user'):
        request._cached_user = get_user_object(request)
    return request._cached_user


class AuthenticationMiddleware(AuthenticationMiddleware):
    def process_request(self, request):

        assert hasattr(request, 'session'), (
            "The djangae.contrib.googleauth middleware requires session middleware "
            "to be installed. Edit your MIDDLEWARE%s setting to insert "
            "'django.contrib.sessions.middleware.SessionMiddleware' before "
            "'djangae.contrib.googleauth.middleware.AuthenticationMiddleware'."
        ) % ("_CLASSES" if settings.MIDDLEWARE is None else "")

        request.user = SimpleLazyObject(lambda: get_user(request))

        # See if the handling view is marked with the auth_middleware_exempt
        # decorator, and return if so.
        if request.resolver_match:
            func = request.resolver_match.func
            exempt = getattr(func, "_auth_middleware_exempt", False)
            if exempt:
                return None

        backend_str = request.session.get(BACKEND_SESSION_KEY)

        if request.user.is_authenticated:
            if backend_str and isinstance(load_backend(backend_str), OAuthBackend):

                # Should we link the Django session to the OAuth session? In most cases we shouldn't
                # as oauth would've been used for identification at login only.
                expire_session = getattr(settings, _OAUTH_LINK_EXPIRY_SETTING, False)

                if expire_session:
                    # The user is authenticated with Django, and they use the OAuth backend, so they
                    # should have a valid oauth session
                    oauth_session = OAuthUserSession.objects.filter(
                        pk=request.user.google_oauth_id
                    ).first()

                    # Their oauth session does not exist, so let's log them out
                    if not oauth_session:
                        logout(request)
                        return None

                    # Their oauth session expired but we still have an active user session
                    if not oauth_session.is_valid:
                        return redirect(
                            reverse("googleauth_oauth2login") + '?' + urlencode(dict(next=request.path))
                        )

            elif backend_str and isinstance(load_backend(backend_str), IAPBackend):
                if not IAPBackend.can_authenticate(request):
                    logout(request)
        else:
            backends = get_backends()
            try:
                iap_backend = next(filter(lambda be: isinstance(be, IAPBackend), backends))
            except StopIteration:
                iap_backend = None

            # Try to authenticate with IAP if the headers are available
            if iap_backend and IAPBackend.can_authenticate(request):
                auth_with_iap(iap_backend, request)


# A `retry_on_error` is needed here because few Datastore transactions
# might collide in the iap auth flow.
#
# Sessions
# If multiple concurrent calls hit the server and the Session needs its key to be cycled
# we could have contention. Interestingly at the time of adding the retry the collision happens because of
# the Gcloudc INSERT being wrapped in a transaction.
#
# User
# User creation might happen in the IAP backend authentication method and this
# can create contention.
# User can also get updates in particular scenarios (see the IAP backend) which can lead to contention.
@retry_on_error(_catch=DatabaseError, _attempts=10, _initial_wait=200, _max_wait=600)
def auth_with_iap(iap_backend, request):
    # Calling login() cycles the csrf token which causes POST request
    # to break. We only call login if authenticating with IAP changed
    # the user ID in the session, or the user ID was not in the session
    # at all.
    user = iap_backend.authenticate(request)
    if user and user.is_authenticated:
        should_login = (
            SESSION_KEY not in request.session
            or _get_user_session_key(request) != user.pk
        )

        # We always set the backend to IAP so that it truely reflects what was the last
        # backend to authenticate this user
        user.backend = 'djangae.contrib.googleauth.backends.iap.%s' % IAPBackend.__name__

        if should_login:
            # Setting the backend is needed for the call to login
            login(request, user)
        else:
            # If we don't call login, we need to set request.user ourselves
            # and update the backend string in the session
            request.user = user
            if request.session[BACKEND_SESSION_KEY] != user.backend:
                # Avoid an unnecessary call to `session.save()`
                # which can cause contention (see #1367)
                request.session[BACKEND_SESSION_KEY] = user.backend


class ProfileForm(forms.Form):
    email = forms.EmailField()
    is_superuser = forms.BooleanField(
        initial=False,
        required=False
    )


_CREDENTIALS_FILE = os.path.join(
    settings.BASE_DIR, ".iap-credentials"
)


def _login_view(request):
    if request.method == "POST":
        form = ProfileForm(request.POST)
        if form.is_valid():
            # We write a credentials file for 2 reasons:
            # 1. It will persist across local server restarts.
            # 2. It will blow up on production, as the local folder
            #    is not writable.
            with open(_CREDENTIALS_FILE, "w") as f:
                f.write(
                    "%s\n%s\n" % (
                        form.cleaned_data["email"],
                        form.cleaned_data["is_superuser"],
                    )
                )

            dest = request.GET.get(REDIRECT_FIELD_NAME, "/")
            return HttpResponseRedirect(dest)
    else:
        form = ProfileForm()

    subs = {
        "form": form
    }

    return render(request, "googleauth/dev_login.html", subs)


def id_from_email(email):
    """
        Just generates a predictable user ID from the email entered
    """
    md5 = hashlib.md5()
    md5.update(email.encode("utf-8"))

    # Truncate to 32-bit
    return int(md5.hexdigest(), 16) & 0xFFFFFFFF


def local_iap_login_middleware(get_response):
    User = get_user_model()

    def middleware(request):
        request._through_local_iap_middleware = True

        if is_production_environment():
            logger.warning(
                "local_iap_login_middleware is for local development only, "
                "and will not work on production. "
                "You should remove it from your MIDDLEWARE setting"
            )
            response = get_response(request)
        elif request.path == "/_dj/login/":
            response = _login_view(request)
        elif request.path == "/_dj/logout/":
            if os.path.exists(_CREDENTIALS_FILE):
                os.remove(_CREDENTIALS_FILE)

            if REDIRECT_FIELD_NAME in request.GET:
                return HttpResponseRedirect(request.GET[REDIRECT_FIELD_NAME])
            else:
                return HttpResponseRedirect("/_dj/login/")
        else:
            if os.path.exists(_CREDENTIALS_FILE):
                # Update the request headers with the stored credentials
                with open(_CREDENTIALS_FILE, "r") as f:
                    data = f.readline()
                    email = data.strip()

                    # Set is_superuser according to the
                    # data in the credentials file.
                    data = f.readline()
                    is_superuser = data.strip() == "True"
                    google_iap_id = id_from_email(email)

                    defaults = dict(
                        is_superuser=is_superuser,
                        email=email,
                        google_iap_id=str(google_iap_id),  # Saved as string in the db
                        google_iap_namespace="auth.example.com",
                        username=f'google_iap_user:{google_iap_id}',
                    )

                    if is_superuser:
                        defaults["is_staff"] = True

                    try:
                        user = User.objects.get(email_lower=email.lower())
                        original_dict = user.__dict__.copy()

                        for field, value in defaults.items():
                            setattr(user, field, value)

                        # Comparing __dict__ before and after should be ok, since the extra "_state"
                        # is the same object. We may end up with some false positive if this changes
                        # in the future, which is ok.
                        if original_dict != user.__dict__:
                            retry(
                                user.save,
                                _catch=DatabaseError,
                                _attempts=10,
                                _initial_wait=200,
                                _max_wait=600,
                            )
                    except User.DoesNotExist:
                        user = User.objects.create(email_lower=email.lower(), **defaults)

                    request.META[_GOOG_JWT_ASSERTION_HEADER] = "JWT TOKEN"
                    request.META[_GOOG_AUTHENTICATED_USER_ID_HEADER] = "auth.example.com:%s" % user.google_iap_id
                    request.META[_GOOG_AUTHENTICATED_USER_EMAIL_HEADER] = "auth.example.com:%s" % email

            response = get_response(request)

        return response
    return middleware


LocalIAPLoginMiddleware = local_iap_login_middleware
