from unittest.mock import patch

from django.db import models
from djangae.contrib import sleuth
from djangae.test import TestCase
from djangae.utils import get_client_ip, get_next_available_port, retry, retry_on_error


class AvailablePortTests(TestCase):

    def test_get_next_available_port(self):
        url = "127.0.0.1"
        port = 8091
        self.assertEquals(8091, get_next_available_port(url, port))
        with sleuth.switch(
            "djangae.utils.port_is_open",
            lambda *args, **kwargs: False if args[1] < 8095 else True
        ):
            self.assertEquals(8095, get_next_available_port(url, port))


class EnsureCreatedModel(models.Model):
    field1 = models.IntegerField()

    class Meta:
        app_label = "djangae"

    def __str__(self):
        return u"PK: {}, field1 {}".format(self.pk, self.field1)


class RetryTestCase(TestCase):
    """ Tests for djangae.utils.retry.
        We test the retry_on_error decorator because it tests `retry` by proxy.
    """

    def test_attempts_param(self):
        """ It should only try a maximum of the number of times specified. """

        @retry_on_error(_attempts=2, _initial_wait=0, _catch=Exception)
        def flakey():
            flakey.attempts += 1
            raise Exception("Oops")

        flakey.attempts = 0

        self.assertRaises(Exception, flakey)  # Should fail eventually, after 2 attempts
        self.assertEqual(flakey.attempts, 2)

    def test_catch_param(self):
        """ It should only catch the exceptions given. """

        def flakey():
            flakey.attempts += 1
            raise ValueError("Oops")

        flakey.attempts = 0

        # If we only except TypeError then ValueError should raise immediately
        self.assertRaises(ValueError, retry_on_error(_catch=TypeError)(flakey))
        self.assertEqual(flakey.attempts, 1)  # Only 1 attempt should have been made
        # With the correct _catch param, it should catch our exception
        flakey.attempts = 0  # reset
        self.assertRaises(ValueError, retry_on_error(_catch=ValueError, _initial_wait=0, _attempts=5)(flakey))
        self.assertEqual(flakey.attempts, 5)

    def test_initial_wait_param(self):
        """ The _initial_wait parameter should determine the backoff time for retries, which
            should be doubled for each subsequent retry.
        """

        @retry_on_error(_initial_wait=5, _attempts=3, _catch=Exception, _avoid_clashes=False)
        def flakey():
            raise Exception("Oops")

        with sleuth.watch("djangae.utils._yield") as sleep_watch:
            try:
                flakey()
            except Exception:
                pass

            self.assertEqual(len(sleep_watch.calls), 2)  # It doesn't sleep after the final attempt
            self.assertEqual(sleep_watch.calls[0].args[0], 0.005)  # initial wait in milliseconds
            self.assertEqual(sleep_watch.calls[1].args[0], 0.01)  # initial wait doubled

    def test_max_wait_param(self):
        """ The _max_wait parameter should limit the backoff time for retries, otherwise they will
            keep on doubling.
        """

        @retry_on_error(_initial_wait=1, _max_wait=3, _attempts=10, _catch=Exception)
        def flakey():
            raise Exception("Oops")

        with sleuth.watch("djangae.utils._yield") as sleep_watch:
            try:
                flakey()
            except Exception:
                pass

            self.assertTrue(sleep_watch.called)
            self.assertEqual(sleep_watch.call_count, 9)  # It doesn't sleep after the final attempt
            sleep_times = [call.args[0] for call in sleep_watch.calls]
            self.assertEqual(max(sleep_times), 0.003)

    def test_args_and_kwargs_passed(self):
        """ Args and kwargs passed to `retry` or to the function decorated with `@retry_on_error`
            should be passed to the wrapped function.
        """

        def flakey(a, b, c=None):
            self.assertEqual(a, 1)
            self.assertEqual(b, 2)
            self.assertEqual(c, 3)

        retry(flakey, 1, 2, c=3)
        retry_on_error()(flakey)(1, 2, c=3)


class FakeIpRequest:
    def __init__(self, xff, remote_addr):
        self.META = {
            'HTTP_X_FORWARDED_FOR': xff,
            'REMOTE_ADDR': remote_addr
        }


class ClientIpTestCase(TestCase):

    def test_1_proxy_default(self):
        self.assertEqual(get_client_ip(FakeIpRequest('5.5.5.5', '169.254.1.1')), '5.5.5.5')

    def test_missing_xff(self):
        self.assertEqual(get_client_ip(FakeIpRequest(None, '169.254.1.1')), '169.254.1.1')

    def test_fake_xff(self):
        self.assertEqual(get_client_ip(FakeIpRequest('bad_guy, 5.5.5.5', '169.254.1.1')), '5.5.5.5')

    @patch('django.conf.settings.NUM_PROXIES', 2)
    def test_2_proxies_configured(self):
        self.assertEqual(get_client_ip(FakeIpRequest('0.1.0.2, 169.254.1.1', '169.254.1.1')), '0.1.0.2')

    @patch('django.conf.settings.NUM_PROXIES', None)
    def test_no_proxies_allowed(self):
        self.assertEqual(get_client_ip(FakeIpRequest('bad_guy, ignore_me', '5.5.5.5')), '5.5.5.5')

    @patch('django.conf.settings.NUM_PROXIES', 2)
    def test_proxies_overestimated(self):
        self.assertEqual(get_client_ip(FakeIpRequest('5.5.5.5', '169.254.1.1')), '5.5.5.5')
