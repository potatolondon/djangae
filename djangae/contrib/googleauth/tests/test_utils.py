from django.db import models
from django.contrib.auth import get_user_model
from django.test import override_settings
from djangae.test import TestCase
from djangae.contrib.googleauth.backends import _generate_unused_username


class SwappedUserModel(models.Model):
    username = models.CharField(max_length=50)
    username_lower = models.CharField(max_length=50)


class GenerateUnusedUsernameTestCase(TestCase):
    def test_should_return_ideal_username_if_none_exist(self):
        ideal = 'firstname.lastname'
        unused_username = _generate_unused_username(ideal)

        # The generated unused username should match the ideal username
        self.assertEqual(unused_username, ideal)

    def test_should_return_unique_username_if_ideal_already_exist(self):
        ideal = 'firstname.lastname'

        UserModel = get_user_model()
        UserModel.objects.create(email=f"{ideal}@xyz.com", username=ideal)

        unused_username = _generate_unused_username(ideal)

        # The generated unused username should differ from the
        # ideal username because it already exist.
        self.assertNotEqual(unused_username, ideal)

    @override_settings(AUTH_USER_MODEL="googleauth.SwappedUserModel")
    def test_should_return_unique_username_if_ideal_already_exist_and_auth_model_is_swapped(self):
        ideal = 'firstname.lastname'

        UserModel = get_user_model()

        # Create a User with the username
        UserModel.objects.create(username=ideal, username_lower=ideal.lower())

        unused_username = _generate_unused_username(ideal)

        # The generated unused username should differ from the ideal
        self.assertNotEqual(unused_username, ideal)
