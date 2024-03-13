import concurrent.futures
from unittest.mock import (
    ANY,
    patch,
)

from django.conf import settings
from django.contrib.auth import get_user_model, SESSION_KEY
from django.core.exceptions import ImproperlyConfigured
from django.http.response import HttpResponse
from django.test.utils import override_settings
from django.urls import path

from djangae.contrib import sleuth
from djangae.test import TestCase

User = get_user_model()

urlpatterns = [
    path('', lambda request: HttpResponse('Ok'), name='index')
]


def authenticate(verify_token_mock, client, google_iap_id=999, user_email='test@example.com'):
    verify_token_mock.return_value = {
        'sub': f'auth.example.com:{google_iap_id}',
        'email': user_email,
    }

    headers = {
        'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{google_iap_id}',
        'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
        'HTTP_X_GOOG_IAP_JWT_ASSERTION': 'JWT',
    }

    return client.get("/", **headers)


@override_settings(ROOT_URLCONF=__name__, GOOGLEAUTH_IAP_JWT_AUDIENCE="something")
class IAPAuthenticationTests(TestCase):

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_user_created_if_authenticated(self, verify_token_mock):
        user = '99999'
        user_email = 'test@example.com'
        verify_token_mock.return_value = {
            'sub': f'auth.example.com:{user}',
            'email': user_email,
        }

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': 'JWT',
        }

        self.client.get("/", **headers)

        self.assertTrue(User.objects.exists())

        user = User.objects.get()

        self.assertEqual(user.google_iap_id, '99999')
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.username, 'test')
        self.assertFalse(user.has_usable_password())

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_email_change(self, verify_token_mock):
        user = '99999'
        user_email = 'test@example.com'
        verify_token_mock.return_value = {
            'sub': f'auth.example.com:{user}',
            'email': user_email,
        }

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': 'JWT',
        }

        self.client.get("/", **headers)

        self.assertTrue(User.objects.exists())

        user = User.objects.get()

        self.assertEqual(user.google_iap_id, '99999')
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.username, 'test')

        user = '99999'
        user_email = 'test22@example.com'
        verify_token_mock.return_value = {
            'sub': f'auth.example.com:{user}',
            'email': user_email,
        }

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': 'JWT',
        }

        self.client.get("/", **headers)

        user = User.objects.get()

        self.assertEqual(user.google_iap_id, '99999')
        self.assertEqual(user.email, 'test22@example.com')

        # Username not updated
        self.assertEqual(user.username, 'test')

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_email_case_insensitive(self, verify_token_mock):
        """
            Even though the RFC says that the part of an email
            address before the '@' is case sensitive, basically no
            mail provider does that, and to allow differences in case
            causes more issues than it solves, so we ensure that although
            we retain the original case of an email, you can't create different
            users with emails that differ in case alone.
        """

        user = User.objects.create(
            email='test22@example.com'
        )

        self.assertFalse(user.password)
        self.assertEqual(user.email, 'test22@example.com')

        user = '99999'
        user_email = 'tESt22@example.com'
        verify_token_mock.return_value = {
            'sub': f'auth.example.com:{user}',
            'email': user_email,
        }

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': 'JWT',
        }

        self.client.get("/", **headers)

        user = User.objects.get()

        self.assertEqual(user.email, 'tESt22@example.com')
        self.assertTrue(user.password)  # Should've set an unusable password

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_email_case_sensitive_fallback(self, verify_token_mock):
        """
            Even though we try to find users by email_lower - there are occasions
            where this calculated field might not have been populated yet (e.g.
            a move to using contrib.googleauth from another system). For this
            reason we should do a final fallback search for case-sensitive email
            matches.
        """

        user = User.objects.create(
            email='tESt22@example.com'
        )

        User.objects.update(email_lower="")
        user.refresh_from_db()

        self.assertEqual(user.email, 'tESt22@example.com')
        self.assertEqual(user.email_lower, "")

        user = '99999'
        user_email = 'tESt22@example.com'
        verify_token_mock.return_value = {
            'sub': f'auth.example.com:{user}',
            'email': user_email,
        }

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': 'JWT',
        }

        self.client.get("/", **headers)

        user = User.objects.get()

        self.assertEqual(user.email, 'tESt22@example.com')
        self.assertEqual(user.email_lower, 'test22@example.com')

    @override_settings()
    def test_raises_if_missing_setting(self):
        user = '99999'
        user_email = 'tESt22@example.com'

        del settings.GOOGLEAUTH_IAP_JWT_AUDIENCE

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': 'JWT',
        }
        with self.assertRaises(ImproperlyConfigured):
            self.client.get("/", **headers)

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_validates_jwt_correctly(self, verify_token_mock):
        user = '99999'
        user_email = 'tESt22@example.com'
        JWT = 'JWT'

        verify_token_mock.return_value = {
            'sub': f'auth.example.com:{user}',
            'email': user_email,
        }

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': JWT,
        }

        self.client.get("/", **headers)

        verify_token_mock.assert_called_with(
            JWT,
            ANY,
            audience="something",
            certs_url='https://www.gstatic.com/iap/verify/public_key'
        )

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_raises_if_validation_fails(self, verify_token_mock):
        user = '99999'
        user_email = 'tESt22@example.com'
        JWT = 'JWT'

        verify_token_mock.side_effect = ValueError()

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': JWT,
        }

        response = self.client.get("/", **headers)
        self.assertEqual(response.status_code, 400)

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_raises_if_user_id_does_not_match(self, verify_token_mock):
        user = '99999'
        user_email = 'tESt22@example.com'
        JWT = 'JWT'

        verify_token_mock.return_value = {
            'sub': f'auth.example.com:{user}',
            'email': user_email,
        }

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': 'auth.example.com:somethingelse',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': JWT,
        }

        with self.assertRaises(AssertionError):
            self.client.get("/", **headers)

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_raises_if_email_does_not_match(self, verify_token_mock):
        user = '99999'
        user_email = 'tESt22@example.com'
        JWT = 'JWT'

        verify_token_mock.return_value = {
            'sub': f'auth.example.com:{user}',
            'email': user_email,
        }

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': 'auth.example.com:another@email.com',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': JWT,
        }

        with self.assertRaises(AssertionError):
            self.client.get("/", **headers)

    @override_settings()
    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_no_validation_if_local_iap(self, verify_token_mock):

        settings.MIDDLEWARE.insert(
            settings.MIDDLEWARE.index('djangae.contrib.googleauth.middleware.AuthenticationMiddleware'),
            'djangae.contrib.googleauth.middleware.LocalIAPLoginMiddleware',
        )

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': 'auth.example.com:somethingelse',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': 'auth.example.com:another@email.com',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': 'JWT',
        }

        response = self.client.get("/", **headers)
        verify_token_mock.assert_not_called()
        self.assertEqual(response.status_code, 200)
        settings.MIDDLEWARE.remove(
            'djangae.contrib.googleauth.middleware.LocalIAPLoginMiddleware'
        )

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_login_called_when_necessary(self, verify_token_mock):
        """
            login should only be called if:

             - There is no user ID stored in request.session
             - The user ID in request.session does not match
        """

        user = '99999'
        user_email = 'test@example.com'
        verify_token_mock.return_value = {
            'sub': f'auth.example.com:{user}',
            'email': user_email,
        }

        headers = {
            'HTTP_X_GOOG_AUTHENTICATED_USER_ID': f'auth.example.com:{user}',
            'HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL': f'auth.example.com:{user_email}',
            'HTTP_X_GOOG_IAP_JWT_ASSERTION': 'JWT',
        }

        # First authentication, login should be called
        with sleuth.watch("djangae.contrib.googleauth.middleware.login") as login:
            self.client.get("/", **headers)
            self.assertTrue(User.objects.exists())
            self.assertTrue(login.called)

        # Already logged-in, login shouldn't be called
        with sleuth.watch("djangae.contrib.googleauth.middleware.login") as login:
            self.client.get("/", **headers)
            self.assertFalse(login.called)

        session = self.client.session
        session[SESSION_KEY] = 1
        session.save()

        # Mismatched user ID, login should be called again
        with sleuth.watch("djangae.contrib.googleauth.middleware.login") as login:
            self.client.get("/", **headers)
            self.assertTrue(login.called)

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_concurrent_authenticate_new_user(self, verify_token_mock):
        concurrent_writes = 5
        futures = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_writes) as executor:
            for _ in range(concurrent_writes):
                futures.append(executor.submit(authenticate, verify_token_mock, self.client))
        concurrent.futures.wait(futures)

        auth_results = [future.result() for future in futures]

        [self.assertEqual(r.status_code, 200) for r in auth_results]

    @patch('djangae.contrib.googleauth.backends.iap.id_token.verify_token')
    def test_concurrent_authenticate_existing_iap_user(self, verify_token_mock):
        google_iap_id = 10
        email = 'an_existing_user@example.com'
        User.objects.create(
            email=email,
            google_iap_id=google_iap_id,
            password='a_password'

        )

        self.assertGreater(len(User.objects.filter(google_iap_id=google_iap_id)), 0)

        authenticate(verify_token_mock, self.client, google_iap_id=google_iap_id, user_email=email)

        concurrent_writes = 10
        futures = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_writes) as executor:
            for _ in range(concurrent_writes):
                futures.append(
                    executor.submit(authenticate, verify_token_mock, self.client,
                                    google_iap_id=google_iap_id, user_email=email))
        concurrent.futures.wait(futures)

        auth_results = [future.result() for future in futures]

        [self.assertEqual(r.status_code, 200) for r in auth_results]
