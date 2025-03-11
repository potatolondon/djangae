
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from ..models import (
    AbstractGoogleUser,
    UserManager,
)
from . import (
    _find_atomic_decorator,
    _generate_unused_username,
)
from .base import BaseBackend

User = get_user_model()


class OAuthBackend(BaseBackend):
    def authenticate(self, request, **kwargs):
        atomic = _find_atomic_decorator(User)

        if not issubclass(User, AbstractGoogleUser):
            raise ImproperlyConfigured(
                "OAuthBackend requires AUTH_USER_MODEL to be a "
                " subclass of djangae.contrib.auth.models.AbstractGoogleUser."
            )

        oauth_session = kwargs.get("oauth_session")

        if (not oauth_session) or (not oauth_session.is_valid):
            return

        # FIXME: Refresh the token if it's close to expiry?

        profile = oauth_session.profile

        email = UserManager.normalize_email(profile["email"])
        assert email
        username = email.split("@", 1)[0]

        with atomic():
            # Look for a user, either by oauth session ID, or email
            user = User.objects.filter(
                google_oauth_id=oauth_session.pk
            ).first()

            if not user:
                # Only fallback to email if we didn't find by session ID
                user = User.objects.filter(
                    Q(email_lower=email.lower()) | Q(email=email)
                ).first()

            # So we previously had a user sign in by email, but not
            # via OAuth, so let's update their user with their oauth
            # session ID
            if user:
                if not user.google_oauth_id:
                    user.google_oauth_id = oauth_session.pk
                else:
                    assert (user.google_oauth_id == oauth_session.pk)
                    # We got the user by google_oauth_id, but their email
                    # might have changed (maybe), so update that just in case
                    user.email = email

                if not user.username:
                    user.username = _generate_unused_username(username)

                # If the user doesn't currently have a password, it could
                # mean that this backend has just been enabled on existing
                # data that uses some other authentication system (e.g. the
                # App Engine Users API) - for safety we make sure that an
                # unusable password is set.
                if not user.password:
                    user.set_unusable_password()

                user.save()
            else:
                # First time we've seen this user
                user = User.objects.create(
                    google_oauth_id=oauth_session.pk,
                    email=email,
                    username=_generate_unused_username(username)
                )
                user.set_unusable_password()
                user.save()

        return user

    def user_can_authenticate(self, user):
        """
        Reject users with is_active=False. Custom user models that don't have
        that attribute are allowed.
        """
        is_active = getattr(user, 'is_active', None)
        return is_active or is_active is None

    def get_user(self, user_id):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None
