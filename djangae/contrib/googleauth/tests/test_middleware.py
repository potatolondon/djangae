from django.test.utils import override_settings
from djangae.contrib.googleauth.backends.iap import IAPBackend
from djangae.contrib.googleauth.models import AnonymousUser
from djangae.test import TestCase
from unittest.mock import patch, Mock
from djangae.contrib.googleauth.middleware import AuthenticationMiddleware
from djangae.contrib.googleauth.backends.oauth2 import OAuthBackend
from djangae.contrib.googleauth.models import OAuthUserSession
from django.test import (RequestFactory)
from django.contrib.auth import get_user_model, BACKEND_SESSION_KEY


@override_settings(ROOT_URLCONF=__name__)
class AuthBackendTests(TestCase):

    def setUp(self):
        super().setUp()

        self.middleware = AuthenticationMiddleware(get_response=lambda x: x)
        self.request = RequestFactory().get('/')
        self.request.session = {}
        self.mock_view = Mock(_auth_middleware_exempt=False)

        class ResolverMatch:
            func = self.mock_view

        self.request.resolver_match = ResolverMatch()

    @patch('djangae.contrib.googleauth.middleware.load_backend', return_value=OAuthBackend())
    def test_anonymous_user_if_not_authenticated(self, load_backend_mock):
        self.middleware.process_request(self.request)
        self.assertIsInstance(self.request.user, AnonymousUser)

    @patch('djangae.contrib.googleauth.middleware.IAPBackend.can_authenticate', return_value=True)
    @patch('djangae.contrib.googleauth.middleware.login')
    @patch('djangae.contrib.googleauth.middleware.get_backends')
    def test_user_if_iap_headers(self, get_backends_mock, login_mock, can_auth):
        iap_backend_mock = Mock(spec=IAPBackend)
        user = Mock()
        iap_backend_mock.authenticate.return_value = user
        get_backends_mock.return_value = [iap_backend_mock]

        self.middleware.process_request(self.request)

        can_auth.assert_called_once()
        iap_backend_mock.authenticate.assert_called_once()
        login_mock.assert_called_once_with(self.request, user)

    @patch('djangae.contrib.googleauth.middleware.IAPBackend.can_authenticate', return_value=True)
    @patch('djangae.contrib.googleauth.middleware.login')
    @patch('djangae.contrib.googleauth.middleware.get_backends')
    def test_no_iap_login_if_not_installed(self, get_backends_mock, login_mock, can_auth):
        oauth_backend_mock = Mock(spec=OAuthBackend)
        get_backends_mock.return_value = [oauth_backend_mock]

        self.middleware.process_request(self.request)

        can_auth.assert_not_called()
        login_mock.assert_not_called()

    @override_settings(GOOGLEAUTH_LINK_OAUTH_SESSION_EXPIRY=True)
    @patch('djangae.contrib.googleauth.middleware.get_user')
    @patch('djangae.contrib.googleauth.middleware.logout')
    @patch('djangae.contrib.googleauth.middleware.load_backend')
    def test_oauth_no_oauth_session(self, load_backend_mock, logout_mock, get_user_mock):
        # Session has an authenticated user
        user_mock = Mock(spec=get_user_model())
        user_mock.is_authenticated = True
        user_mock.google_oauth_id = '1'
        get_user_mock.return_value = user_mock

        # It has a session that uses oauth
        OAUTH_SESSION_KEY = 'key'
        self.request.session[BACKEND_SESSION_KEY] = OAUTH_SESSION_KEY

        # Loads the oauth backend
        oauth_backend_mock = Mock(spec=OAuthBackend)
        load_backend_mock.return_value = oauth_backend_mock

        self.middleware.process_request(self.request)

        # Check is loading the right backend
        load_backend_mock.assert_called_once_with(OAUTH_SESSION_KEY)

        # Session does not exist, logging out.
        logout_mock.assert_called_once_with(self.request)

    @override_settings(GOOGLEAUTH_LINK_OAUTH_SESSION_EXPIRY=True)
    @patch('djangae.contrib.googleauth.middleware.OAuthUserSession', spec=OAuthUserSession)
    @patch('djangae.contrib.googleauth.middleware.get_user')
    @patch('djangae.contrib.googleauth.middleware.logout')
    @patch('djangae.contrib.googleauth.middleware.load_backend')
    @patch('djangae.contrib.googleauth.middleware.redirect')
    @patch('djangae.contrib.googleauth.middleware.reverse', return_value="/login/")
    def test_oauth_oauth_session_invalid(self, reverse_mock, redirect_mock, load_backend_mock, logout_mock, get_user_mock, OAuthUserSession_mock): # noqa E501
        # Session has an authenticated user
        user_mock = Mock(spec=get_user_model())
        user_mock.is_authenticated = True
        user_mock.google_oauth_id = '1'
        get_user_mock.return_value = user_mock

        # It has a session that uses oauth
        OAUTH_SESSION_KEY = 'key'
        self.request.session[BACKEND_SESSION_KEY] = OAUTH_SESSION_KEY

        # Loads the oauth backend
        oauth_backend_mock = Mock(spec=OAuthBackend)
        load_backend_mock.return_value = oauth_backend_mock

        # Loads a OAuthUserSession that is invalid
        invalid_OAuth_session = Mock(OAuthUserSession)
        invalid_OAuth_session.is_valid = False
        OAuthUserSession_mock.objects.filter.return_value.first.return_value = invalid_OAuth_session

        self.middleware.process_request(self.request)

        # Check is getting user
        get_user_mock.assert_called_once_with(self.request)

        # Check is loading the right backend
        load_backend_mock.assert_called_once_with(OAUTH_SESSION_KEY)

        # Check is fetching the right session with
        OAuthUserSession_mock.objects.filter.assert_called_once_with(pk=self.request.user.google_oauth_id)

        # Session does not exist, logging out.
        logout_mock.assert_not_called()

        # Test redirects to login
        redirect_mock.assert_called_once_with("/login/?next=%2F")

    @override_settings(GOOGLEAUTH_LINK_OAUTH_SESSION_EXPIRY=True)
    @patch('djangae.contrib.googleauth.middleware.OAuthUserSession', spec=OAuthUserSession)
    @patch('djangae.contrib.googleauth.middleware.get_user')
    @patch('djangae.contrib.googleauth.middleware.logout')
    @patch('djangae.contrib.googleauth.middleware.load_backend')
    def test_oauth_oauth_session_valid(self, load_backend_mock, logout_mock, get_user_mock, OAuthUserSession_mock):
        # Session has an authenticated user
        user_mock = Mock(spec=get_user_model())
        user_mock.is_authenticated = True
        user_mock.google_oauth_id = '1'
        get_user_mock.return_value = user_mock

        # It has a session that uses oauth
        OAUTH_SESSION_KEY = 'key'
        self.request.session[BACKEND_SESSION_KEY] = OAUTH_SESSION_KEY

        # Loads the oauth backend
        oauth_backend_mock = Mock(spec=OAuthBackend)
        load_backend_mock.return_value = oauth_backend_mock

        # Loads a OAuthUserSession that is valid
        valid_OAuth_session = Mock(OAuthUserSession)
        valid_OAuth_session.is_valid = True
        OAuthUserSession_mock.objects.filter.return_value.first.return_value = valid_OAuth_session

        self.middleware.process_request(self.request)

        # Check is getting user
        get_user_mock.assert_called_once_with(self.request)

        # Check is loading the right backend
        load_backend_mock.assert_called_once_with(OAUTH_SESSION_KEY)

        # Check is fetching the right session with
        OAuthUserSession_mock.objects.filter.assert_called_once_with(pk=self.request.user.google_oauth_id)

        # Session does not exist, logging out.
        logout_mock.assert_not_called()

    @patch('djangae.contrib.googleauth.middleware.IAPBackend.can_authenticate', return_value=False)
    @patch('djangae.contrib.googleauth.middleware.get_user')
    @patch('djangae.contrib.googleauth.middleware.logout')
    @patch('djangae.contrib.googleauth.middleware.load_backend')
    def test_iap_iap_cant_authenticate(
        self,
        load_backend_mock,
        logout_mock,
        get_user_mock,
        can_authenticate_mock
    ):
        # Session has an authenticated user
        user_mock = Mock(spec=get_user_model())
        user_mock.is_authenticated = True
        get_user_mock.return_value = user_mock

        # It has a session_str
        OAUTH_SESSION_KEY = 'key'
        self.request.session[BACKEND_SESSION_KEY] = OAUTH_SESSION_KEY

        # Loads the iap backend
        iap_backend_mock = Mock(spec=IAPBackend)
        load_backend_mock.return_value = iap_backend_mock

        self.middleware.process_request(self.request)

        # Logging out.
        logout_mock.assert_called_once_with(self.request)

    @patch('djangae.contrib.googleauth.middleware.IAPBackend.can_authenticate', return_value=True)
    @patch('djangae.contrib.googleauth.middleware.get_user')
    @patch('djangae.contrib.googleauth.middleware.logout')
    @patch('djangae.contrib.googleauth.middleware.load_backend')
    def test_iap_iap_session_valid(
        self,
        load_backend_mock,
        logout_mock,
        get_user_mock,
        can_authenticate_mock
    ):
        # Session has an authenticated user
        user_mock = Mock(spec=get_user_model())
        user_mock.is_authenticated = True
        get_user_mock.return_value = user_mock

        # It has a session_str
        OAUTH_SESSION_KEY = 'key'
        self.request.session[BACKEND_SESSION_KEY] = OAUTH_SESSION_KEY

        # Loads the iap backend
        iap_backend_mock = Mock(spec=IAPBackend)
        load_backend_mock.return_value = iap_backend_mock

        self.middleware.process_request(self.request)

        # Logging out.
        logout_mock.assert_not_called()
