import json
from unittest.mock import (
    Mock,
    create_autospec,
    patch,
)

from django.contrib import auth
from django.contrib.sessions.middleware import SessionMiddleware
from django.test.client import RequestFactory
from django.test.utils import override_settings
from django.urls import reverse
from requests_oauthlib import OAuth2Session

from djangae.contrib.googleauth import _SCOPE_SESSION_KEY
from djangae.contrib.googleauth.models import (
    AnonymousUser,
    OAuthUserSession,
    User,
)
from djangae.contrib.googleauth.views import (
    STATE_SESSION_KEY,
    oauth_login,
)
from djangae.test import TestCase

host = "test.appspot.com"
state_str = "state"
authorization_url = "http://authorization_url.com"


@override_settings(ROOT_URLCONF="djangae.contrib.googleauth.urls", ALLOWED_HOSTS=[host])
class LoginViewTestCase(TestCase):
    """Tests for djangae.contrib.backup.views"""

    def setUp(self):
        super().setUp()
        self.next_url = "go/here"
        self.client.defaults["HTTP_HOST"] = host
        self.login_url = "{}?next={}".format(reverse("googleauth_oauth2login"), self.next_url)

        # Patch oauth session
        self.oAuthSessionMock = create_autospec(OAuth2Session)
        self.oAuthSessionMock.authorization_url.return_value = (authorization_url, state_str,)
        self.oAuthSessionMock.new_state.return_value = state_str
        self.oAuthSessionMock.scope = []
        self.patcher = patch(
            'djangae.contrib.googleauth.views.OAuth2Session',
            Mock(return_value=self.oAuthSessionMock)
        )
        self.OAuthSessionMock = self.patcher.start()

    def tearDown(self):
        super().tearDown()
        self.patcher.stop()

    def test_store_next_url_in_session(self, ):
        """Tests it persists next in the session"""

        self.client.get(self.login_url)
        self.assertEqual(self.client.session[auth.REDIRECT_FIELD_NAME], self.next_url)

    @patch('djangae.contrib.googleauth.views.OAuthUserSession', spec=OAuthUserSession)
    @patch(
        'djangae.contrib.googleauth.views.OAuth2Session.return_value.authorization_url',
        return_value=('url', 'state')
    )
    def test_shows_no_prompt_if_user(self, auth_url_mock, OAuthUserSession_mock):
        """Tests it does not prompt consent screen if user is authenticated with OAuth"""
        user = User.objects.create_user(
            google_oauth_id="123",
            username='test',
            email='test@domain.com'
        )
        request = RequestFactory().get('', HTTP_HOST=host)

        OAuth_session = Mock(OAuthUserSession)
        OAuth_session.is_valid = True
        OAuth_session.scopes = []
        OAuthUserSession_mock.objects.filter.return_value.first.return_value = OAuth_session

        # adding session
        middleware = SessionMiddleware(get_response=lambda x: x)
        middleware.process_request(request)
        request.session.save()

        request.user = user
        oauth_login(request)

        auth_url_mock.assert_called_once()

        self.assertEqual(auth_url_mock.call_args[1]['prompt'], 'none')

    @patch('djangae.contrib.googleauth.views.OAuthUserSession', spec=OAuthUserSession)
    @patch(
        'djangae.contrib.googleauth.views.OAuth2Session.return_value.authorization_url',
        return_value=('url', 'state')
    )
    def test_shows_prompt_if_user_with_addional_scopes(self, auth_url_mock, OAuthUserSession_mock):
        """It prompts consent screen if user is authenticated but additional scopes are required"""
        user = User.objects.create_user(
            google_oauth_id="123",
            username='test',
            email='test@domain.com'
        )
        OAuth_session = Mock(OAuthUserSession)
        OAuth_session.is_valid = True
        OAuth_session.scopes = []
        request = RequestFactory().get('', HTTP_HOST=host)

        # adding session
        middleware = SessionMiddleware(get_response=lambda x: x)

        middleware.process_request(request)
        request.session.save()
        request.user = user
        self.oAuthSessionMock.scope = ['extra']

        oauth_login(request)

        auth_url_mock.assert_called_once()
        self.assertEqual(auth_url_mock.call_args[1]['prompt'], 'select_account')

    @patch(
        'djangae.contrib.googleauth.views.OAuth2Session.return_value.authorization_url',
        return_value=('url', 'state')
    )
    def test_shows_prompt_if_anon_user(self, auth_url_mock):
        """Tests it does prompt consent screen if user is AnonymousUser"""
        user = AnonymousUser()
        request = RequestFactory().get('', HTTP_HOST=host)

        # adding session
        middleware = SessionMiddleware(get_response=lambda x: x)
        middleware.process_request(request)
        request.session.save()

        request.user = user
        oauth_login(request)

        auth_url_mock.assert_called_once()
        self.assertEqual(auth_url_mock.call_args[1]['prompt'], 'select_account')

    @patch(
        'djangae.contrib.googleauth.views.OAuth2Session.return_value.authorization_url',
        return_value=('url', 'state')
    )
    def test_shows_prompt_if_not_user(self, auth_url_mock):
        """Tests it does not prompt consent screen if user is authenticated"""

        self.client.get(self.login_url)

        auth_url_mock.assert_called_once()
        self.assertEqual(auth_url_mock.call_args[1]['prompt'], 'select_account')

    @override_settings(GOOGLEAUTH_CLIENT_ID="clientid", )
    def test_create_a_oauth_session(self, ):
        """Tests it creates a oauth session"""
        self.client.get(self.login_url)

        self.OAuthSessionMock.assert_called_once()
        client_id = self.OAuthSessionMock.call_args[0][0]
        self.assertEqual(client_id, "clientid")

    def test_create_a_oauth_session_with_oauth_scopes(self, ):
        """Tests it creates a oauth session with required scopes"""

        self.client.get(self.login_url)

        self.OAuthSessionMock.assert_called_once()
        scope = self.OAuthSessionMock.call_args[1]["scope"]
        self.assertEqual(set(scope), {"openid", "profile", "email", })

    @override_settings(GOOGLEAUTH_OAUTH_SCOPES=["email", "somethingelse"])
    def test_create_a_oauth_session_with_settings_scopes(self, ):
        """Tests it creates a oauth session with provided scopes"""

        self.client.get(self.login_url)

        self.OAuthSessionMock.assert_called_once()
        scope = self.OAuthSessionMock.call_args[1]["scope"]
        self.assertEqual(set(scope), {"email", "somethingelse"})

    def test_create_a_oauth_session_with_additional_scopes(self, ):
        """Tests it creates a oauth session with addtional scopes"""
        session = self.client.session
        session[_SCOPE_SESSION_KEY] = (["additional"], False)
        session.save()

        self.client.get(self.login_url)

        self.OAuthSessionMock.assert_called_once()
        scope = self.OAuthSessionMock.call_args[1]["scope"]
        self.assertEqual(set(scope), {"openid", "profile", "email", "additional"})

    @override_settings(GOOGLEAUTH_OAUTH_REDIRECT_HOST="redirect.appspot.com", )
    def test_create_a_oauth_session_with_oauth_redirect_provided(self, ):
        """Tests it creates a oauth session with the redirect provided in settings"""
        self.client.get(self.login_url)

        self.OAuthSessionMock.assert_called_once()
        redirect = self.OAuthSessionMock.call_args[1]["redirect_uri"]
        self.assertEqual(redirect, f"http://redirect.appspot.com{reverse('googleauth_oauth2callback')}")

    def test_create_a_oauth_session_with_oauth_redirect(self, ):
        """Tests it creates a oauth session with the redirect using application host"""
        self.client.get(self.login_url)

        self.OAuthSessionMock.assert_called_once()
        redirect = self.OAuthSessionMock.call_args[1]["redirect_uri"]
        self.assertIn(host, redirect)

    def test_stores_state_in_session(self, ):
        """Tests it stores auth state in session"""
        self.client.get(self.login_url)
        self.assertEqual(self.client.session[STATE_SESSION_KEY], state_str)

    def test_stores_host_in_state(self, ):
        """Tests it stores auth hostname in session"""
        self.client.get(self.login_url)

        self.oAuthSessionMock.authorization_url.assert_called_once()
        state = json.loads(self.oAuthSessionMock.authorization_url.call_args[1]['state'])
        self.assertEqual(state['hostname'], host)

    def test_redirects_to_auth_url(self, ):
        """Tests it redirects the user to oauth url"""

        response = self.client.get(self.login_url)
        self.assertRedirects(response, authorization_url, fetch_redirect_response=False)


@override_settings(ROOT_URLCONF="djangae.contrib.googleauth.urls", ALLOWED_HOSTS=[host])
@patch("djangae.contrib.googleauth.views.id_token")
class OAuthCallbackTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.next_url = "go/here"
        self.token = "atoken"
        self.valid_state = json.dumps({
            'token': self.token,
            'hostname': 'app.com',
        })
        self.session = self.client.session
        self.session['next_url'] = "go/here"
        self.session[STATE_SESSION_KEY] = self.token
        self.session.save()
        self.client.defaults["HTTP_HOST"] = host
        self.callback_url = reverse("googleauth_oauth2callback")

        # Patch oauth session
        self.oAuthSessionMock = create_autospec(OAuth2Session)
        self.oAuthSessionMock.authorization_url.return_value = (authorization_url, state_str,)
        self.oAuthSessionMock.new_state.return_value = state_str
        self.oAuthSessionMock.fetch_token.return_value = {
            'id_token': 'atoken',
            'access_token': 'another_token',
            'token_type': 'sometype',
            'expires_in': 123,
            'scope': ['scope1'],
        }
        self.patcher = patch(
            'djangae.contrib.googleauth.views.OAuth2Session',
            Mock(return_value=self.oAuthSessionMock)
        )
        self.OAuthSessionMock = self.patcher.start()

    def tearDown(self):
        super().tearDown()
        self.patcher.stop()

    def test_bad_request_no_state(self, mock_id_token):
        "Test bad request if state is not provided"
        response = self.client.get(self.callback_url)
        self.assertEqual(response.status_code, 400)

    def test_bad_request_invalid_state(self, mock_id_token):
        "Test bad request if state is invalid"
        response = self.client.get("{}?state=invalidstate".format(self.callback_url))
        self.assertEqual(response.status_code, 400)

    @override_settings(GOOGLEAUTH_OAUTH_REDIRECT_HOST="redirect.com")
    @patch('djangae.contrib.googleauth.views.environment.default_app_host', return_value='default_host.com')
    def test_it_redirects_to_hostname_if_GOOGLEAUTH_OAUTH_REDIRECT_HOST(self, mock_app_host, mock_id_token):
        "Test bad request if state is invalid"
        response = self.client.get(self.callback_url, {
             'state': self.valid_state,
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("http://app.com/oauth2/callback/", response.url)

    def test_bad_request_no_session_state_key(self, mock_id_token):
        "Test bad request if session doesn't have state key"
        del self.session[STATE_SESSION_KEY]
        self.session.save()
        response = self.client.get("{}?state={}".format(self.callback_url, self.valid_state))
        self.assertEqual(response.status_code, 400)

    def test_it_passes_the_default_skew_time(self, mock_id_token):
        "Test verify_oauth2_token is called with correct defaults"
        mock_id_token.verify_oauth2_token.return_value = {
            'sub': '123344',
            'email': 'test@example.com',
        }
        self.client.get(self.callback_url, {
            'state': self.valid_state,
        })

        self.assertEqual(mock_id_token.verify_oauth2_token.call_count, 1)
        self.assertEqual(mock_id_token.verify_oauth2_token.call_args[1]['clock_skew_in_seconds'], 10)

    @override_settings(GOOGLEAUTH_CLOCK_SKEWS_SECONDS=42)
    def test_it_passes_the_overridden_skew_time(self, mock_id_token):
        "Test verify_oauth2_token is called with specified override"
        mock_id_token.verify_oauth2_token.return_value = {
            'sub': '123344',
            'email': 'test@example.com'
        }
        self.client.get(self.callback_url, {
            'state': self.valid_state,
        })

        self.assertEqual(mock_id_token.verify_oauth2_token.call_count, 1)
        self.assertEqual(mock_id_token.verify_oauth2_token.call_args[1]['clock_skew_in_seconds'], 42)
