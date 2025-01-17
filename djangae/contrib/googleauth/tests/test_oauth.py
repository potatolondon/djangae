import json

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.auth.hashers import is_password_usable
from django.http import HttpResponse
from django.shortcuts import reverse
from django.test import (
    LiveServerTestCase,
    RequestFactory,
    override_settings,
)
from django.urls import (
    include,
    path,
)
from django.utils import timezone

from djangae.contrib import sleuth
from djangae.contrib.googleauth.decorators import (
    login_required,
    oauth_scopes_required,
)
from djangae.contrib.googleauth.models import (
    AnonymousUser,
    OAuthUserSession,
    User,
)
from djangae.test import TestCase


class PermissionTests(TestCase):
    pass


@login_required(login_url='/googleauth/oauth2/login/')
def a_protected_view(request):
    return HttpResponse("OK")


urlpatterns = [
    path("protected", a_protected_view),
    path("googleauth/", include("djangae.contrib.googleauth.urls"))
]


class MockedAuth:
    def default(self):
        return MockedCreds(), 'test_project'


class MockedCreds:
    def __init__(self, *args, **kwargs):
        self._client_id = 'xxxxxxx'
        self._client_secret = 'yyyyyy'

    @property
    def client_id(self):
        return self._client_id

    @property
    def client_secret(self):
        return self._client_secret


@override_settings(ROOT_URLCONF=__name__)
class OAuthTests(LiveServerTestCase):

    def test_redirect_to_authorization_url(self):
        """
            Access to a page that is login_required
            should redirect to the authorization url
        """
        live_server_domain = self.live_server_url.split('://')[-1]
        protected_url = '/protected'
        response = self.client.get(protected_url, HTTP_HOST=live_server_domain)
        self.assertTrue(reverse("googleauth_oauth2login") in response.url)
        self.assertEqual(302, response.status_code)

        with sleuth.fake(
            'djangae.contrib.googleauth.views.OAuth2Session.authorization_url',
            return_value=('oauthauthurl', 'oauthstate')
        ) as auth_url:
            response = self.client.get(response.url, HTTP_HOST=live_server_domain)
            # check OAuthSession has been called properly
            self.assertTrue(auth_url.called)
            self.assertEqual(auth_url.calls[0].args[1], 'https://accounts.google.com/o/oauth2/v2/auth')

            self.assertTrue(set({
                "prompt": 'select_account',
                "include_granted_scopes": 'true',
            }.items()).issubset(set(auth_url.calls[0].kwargs.items())))

            self.assertEqual(set(json.loads(auth_url.calls[0].kwargs['state']).keys()), {'hostname', 'token'})

            # check session contains correct keys and values
            self.assertEqual(self.client.session.get('oauth-state'), 'oauthstate')
            self.assertEqual(self.client.session.get('next'), protected_url)

            # check that we're redirecting to authorization url returned from the session instance
            self.assertEqual(response.status_code, 302)
            self.assertTrue('oauthauthurl' in response.url)

    def test_oauth_callback_creates_session(self):
        """
            Should create an oauth session (if valid)
            and then redirect to the correct URL.

            Middleware should take care of authenticating the
            Django session
        """
        pass


@override_settings(ROOT_URLCONF=__name__)
class OAuth2CallbackTests(TestCase):

    def test_session_key_missing_raise_400(self):
        live_server_domain = self.live_server_url.split('://')[-1]
        response = self.client.get(reverse("googleauth_oauth2callback"), HTTP_HOST=live_server_domain)
        self.assertEqual(response.status_code, 400)

    def test_invalid_state_raises_400(self):
        live_server_domain = self.live_server_url.split('://')[-1]
        session = self.client.session
        session['oauth-state'] = 'somestate'
        session.save()
        response = self.client.get(reverse("googleauth_oauth2callback"), HTTP_HOST=live_server_domain)
        self.assertEqual(response.status_code, 400)

    def test_valid_credentials_log_user(self):
        live_server_domain = self.live_server_url.split('://')[-1]
        session = self.client.session
        session['oauth-state'] = 'somestate'
        session[REDIRECT_FIELD_NAME] = '/next_url'
        session.save()

        fake_token = {
            'access_token': '9999',
            'token_type': 'Bearer',
            'expires_in': '30',
            'scope': ['some.scope another.scope'],
            'id_token': 'someencryptedstuff'
        }

        fake_profile = {
            'id': '1',
            'email': 'test@example.com'
        }

        idinfo = {
            'sub': '1',
            'iss': 'accounts.google.com',
            'email': 'test@example.com'
        }

        with sleuth.fake('djangae.contrib.googleauth.views.OAuth2Session.fetch_token', return_value=fake_token), \
                sleuth.fake('djangae.contrib.googleauth.views.OAuth2Session.authorized', return_value=True), \
                sleuth.fake('djangae.contrib.googleauth.views.OAuth2Session.get', return_value=fake_profile), \
                sleuth.watch('djangae.contrib.googleauth.backends.oauth2.OAuthBackend.authenticate') as mocked_auth, \
                sleuth.watch('django.contrib.auth.login') as mocked_login, \
                sleuth.fake('google.oauth2.id_token.verify_token', idinfo):

            state = json.dumps({
                "hostname": "app.com",
            })
            response = self.client.get(
                reverse("googleauth_oauth2callback"),
                data={"state": state},
                HTTP_HOST=live_server_domain
            )

        # check authenticate and login function are called
        self.assertTrue(mocked_auth.called)
        self.assertTrue(mocked_login.called)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(session[REDIRECT_FIELD_NAME] in response.url)

        user = User.objects.get(email="test@example.com")
        self.assertFalse(user.has_usable_password())

    def test_existing_email_has_unusable_password_set(self):
        """
            Log someone in who previously had no password and make sure
            an unusable password was set.
        """

        user = User.objects.create(email="test@example.com")
        self.assertFalse(user.password)
        self.test_valid_credentials_log_user()
        user.refresh_from_db()
        self.assertTrue(user.password)
        self.assertFalse(is_password_usable(user.password))

    @patch('django.contrib.auth.login', autospec=True)
    @patch('django.contrib.auth.authenticate', autospec=True)
    @patch('djangae.contrib.googleauth.views.OAuth2Session', autospec=True)
    def test_unauthorized_credentials_redirect_to_login(self, mocked_session, mocked_auth, mocked_login):
        # set authorized to return False, this should cause a redirect to login, and restart the flow
        mocked_session_instance = mocked_session.return_value
        mocked_session_instance.authorized = False

        live_server_domain = self.live_server_url.split('://')[-1]
        session = self.client.session
        session['oauth-state'] = 'somestate'
        session[REDIRECT_FIELD_NAME] = '/next_url'
        session.save()

        state = json.dumps({
            "hostname": "app.com",
        })
        response = self.client.get(
            reverse("googleauth_oauth2callback"),
            data={"state": state},
            HTTP_HOST=live_server_domain
        )

        # check authenticate and login function are not called
        self.assertFalse(mocked_auth.called)
        self.assertFalse(mocked_login.called)
        # check we're restarting login flow
        self.assertEqual(response.status_code, 302)
        self.assertTrue("/next_url" in response.url)


def a_view(request, *args, **kwargs):
    return HttpResponse(status=200)


@override_settings(ROOT_URLCONF=__name__)
class OAuthScopesRequiredTests(TestCase):
    def setUp(self):
        self._DEFAULT_OAUTH_SCOPES = [
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile"
            ]
        self.factory = RequestFactory()
        self.oauthsession = OAuthUserSession.objects.create(
            id='1' * 21,
            scopes=self._DEFAULT_OAUTH_SCOPES,
            expires_at=timezone.now() + timedelta(seconds=10)
        )
        self.user = User.objects.create_user(
            google_oauth_id=self.oauthsession.pk,
            username='test',
            email='test@domain.com'
        )

    def test_oauth_scopes_required_call_view_if_no_additional_scopes(self):
        """When there are no additional scopes from the one in session, the view is simply called"""
        request = RequestFactory().get('/')
        request.user = self.user

        @oauth_scopes_required(scopes=[])
        def no_scopes_func(*args, **kwargs):
            no_scopes_func.called = True
            no_scopes_func.call_count += 1
        no_scopes_func.called = False
        no_scopes_func.call_count = 0

        @oauth_scopes_required(scopes=self._DEFAULT_OAUTH_SCOPES)
        def scopes_func(*args, **kwargs):
            scopes_func.called = True
            scopes_func.call_count += 1
        scopes_func.called = False
        scopes_func.call_count = 0

        no_scopes_func(request)

        self.assertTrue(no_scopes_func.called)
        self.assertEqual(no_scopes_func.call_count, 1)

        scopes_func(request)
        self.assertTrue(scopes_func.called)
        self.assertEqual(scopes_func.call_count, 1)

    def test_oauth_scopes_required_redirects_to_login_if_anonymous(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()

        middleware = SessionMiddleware(get_response=lambda x: x)
        middleware.process_request(request)
        request.session.save()

        def func(*args, **kwargs):
            func.called = True
        func.called = False

        decorated_func = oauth_scopes_required(scopes=[])(func)
        response_mocked = decorated_func(request)
        self.assertFalse(func.called)
        self.assertEqual(response_mocked.status_code, 302)
        self.assertTrue(reverse("googleauth_oauth2login") in response_mocked.url)

    def test_oauth_scopes_required_redirects_to_login_if_no_oauthsession(self):
        request = RequestFactory().get('/')
        request.user = User.objects.create_user(username='test2', email='test2@domain.com')

        middleware = SessionMiddleware(get_response=lambda x: x)
        middleware.process_request(request)
        request.session.save()

        def func(*args, **kwargs):
            func.called = True
        func.called = False

        decorated_func = oauth_scopes_required(scopes=[])(func)
        response_mocked = decorated_func(request)
        self.assertFalse(func.called)
        self.assertEqual(response_mocked.status_code, 302)
        self.assertTrue(reverse("googleauth_oauth2login") in response_mocked.url)

    def test_oauth_scopes_required_redirects_for_additional_scopes(self):
        scopes = self._DEFAULT_OAUTH_SCOPES + ['https://www.googleapis.com/auth/calendar']
        request = RequestFactory().get('/')
        request.user = self.user

        middleware = SessionMiddleware(get_response=lambda x: x)
        middleware.process_request(request)
        request.session.save()

        def func(*args, **kwargs):
            func.called = True
        func.called = False

        decorated_func_mock = oauth_scopes_required(scopes=scopes)(func)
        response_mocked = decorated_func_mock(request)
        request.session.save()
        self.assertFalse(func.called)
        # check we're redirecting to login url with the correct parameters
        self.assertEqual(response_mocked.status_code, 302)
        self.assertTrue(reverse("googleauth_oauth2login") in response_mocked.url)


class AuthBackendTests(TestCase):
    def test_valid_oauth_session_creates_django_session(self):
        pass

    def test_invalid_oauth_session_logs_out_django(self):
        pass

    def test_backend_does_nothing_if_authed_with_different_backend(self):
        """
            If you have the model backend and oauth backend (for example)
            then we don't log someone out if they authed with the model
            backend

        """
        pass
