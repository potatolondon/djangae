
from django.conf import settings
from django.contrib.auth.base_user import (
    AbstractBaseUser,
    BaseUserManager,
)
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.mail import send_mail
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from gcloudc.db.models.fields.iterable import SetField
from gcloudc.db.models.fields.json import JSONField

from .permissions import PermissionChoiceField


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, username, email, password, **extra_fields):
        """
        Create and save a user with the given username, email, and password.
        """
        if not username:
            raise ValueError('The given username must be set')
        email = self.normalize_email(email)
        username = self.model.normalize_username(username)
        user = self.model(username=username, email=email, **extra_fields)
        user.save(using=self._db)
        return user

    def create_user(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(username, email, password, **extra_fields)


class AnonymousUser:
    id = None
    pk = None
    username = ''
    is_staff = False
    is_active = False
    is_superuser = False

    def __str__(self):
        return 'AnonymousUser'

    def __eq__(self, other):
        return isinstance(other, self.__class__)

    def __hash__(self):
        return 1  # instances always return the same hash value

    def __int__(self):
        raise TypeError('Cannot cast AnonymousUser to int. Are you trying to use it in place of User?')

    def save(self):
        raise NotImplementedError("Djangae doesn't provide a DB representation for AnonymousUser.")

    def delete(self):
        raise NotImplementedError("Djangae doesn't provide a DB representation for AnonymousUser.")

    def set_password(self, raw_password):
        raise NotImplementedError("Djangae doesn't provide a DB representation for AnonymousUser.")

    def check_password(self, raw_password):
        raise NotImplementedError("Djangae doesn't provide a DB representation for AnonymousUser.")

    @property
    def groups(self):
        return self._groups

    @property
    def user_permissions(self):
        return self._user_permissions

    def get_group_permissions(self, obj=None):
        return set()

    def get_all_permissions(self, obj=None):
        return []

    def has_perm(self, perm, obj=None):
        return False

    def has_perms(self, perm_list, obj=None):
        return all(self.has_perm(perm, obj) for perm in perm_list)

    def has_module_perms(self, module):
        return False

    @property
    def is_anonymous(self):
        return True

    @property
    def is_authenticated(self):
        return False

    def get_username(self):
        return self.username


class AbstractGoogleUser(AbstractBaseUser):
    username_validator = UnicodeUsernameValidator()

    # If the user was created via OAuth, this is the oauth ID
    google_oauth_id = models.CharField(
        unique=True,
        blank=True,
        null=True,
        default=None,
        max_length=21
    )

    google_iap_id = models.CharField(
        max_length=150,
        unique=True,
        default=None,
        null=True,
        blank=True
    )

    google_iap_namespace = models.CharField(
        max_length=64,
        default="",
        blank=True,
    )

    username = models.CharField(
        _('username'),
        max_length=150,
        unique=True,
        help_text=_('Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.'),
        validators=[username_validator],
        error_messages={
            'unique': _("A user with that username already exists."),
        },
    )
    first_name = models.CharField(_('first name'), max_length=150, blank=True)
    last_name = models.CharField(_('last name'), max_length=150, blank=True)
    email = models.EmailField(_('email address'), blank=True)
    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin site.'),
    )
    is_superuser = models.BooleanField(
        _('superuser status'),
        default=False,
        help_text=_(
            'Designates that this user has all permissions without '
            'explicitly assigning them.'
        ),
    )
    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)

    # Lower-cased versions of fields for querying on Cloud Datastore
    username_lower = models.CharField(max_length=150, unique=True, editable=False)
    email_lower = models.EmailField(unique=True, editable=False)

    objects = UserManager()

    EMAIL_FIELD = 'email'
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
        abstract = True

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)

    def get_full_name(self):
        """
        Return the first_name plus the last_name, with a space in between.
        """
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        """Return the short name for the user."""
        return self.first_name

    def email_user(self, subject, message, from_email=None, **kwargs):
        """Send an email to this user."""
        send_mail(subject, message, from_email, [self.email], **kwargs)

    def has_perm(self, perm, obj=None):
        from django.contrib.auth.models import _user_has_perm

        # Active superusers have all permissions.
        if self.is_active and self.is_superuser:
            return True

        # Otherwise we need to check the backends.
        return _user_has_perm(self, perm, obj)

    def has_module_perms(self, app_label):
        from django.contrib.auth.models import _user_has_module_perms

        if self.is_active and self.is_superuser:
            return True

        return _user_has_module_perms(self, app_label)

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.username_lower = self.username.lower()
        self.email_lower = self.email.lower()
        super().save(*args, **kwargs)


class User(AbstractGoogleUser):
    pass


class UserPermission(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="permissions"
    )
    permission = PermissionChoiceField()
    obj_id = models.PositiveIntegerField()


class Group(models.Model):
    name = models.CharField(_('name'), max_length=150, unique=True)
    permissions = SetField(
        PermissionChoiceField(),
        blank=True
    )

    def __str__(self):
        return self.name


# Set in the Django session in the oauth2callback. This is used
# by the backend's authenticate() method
_OAUTH_USER_SESSION_SESSION_KEY = "_OAUTH_USER_SESSION_ID"


class OAuthUserSession(models.Model):
    id = models.CharField(max_length=21, primary_key=True)

    access_token = models.CharField(max_length=150, blank=True)
    refresh_token = models.CharField(max_length=150, blank=True)
    id_token = models.CharField(max_length=1500, blank=True)
    token_type = models.CharField(max_length=150, blank=True)

    expires_at = models.DateTimeField()

    scopes = SetField(models.CharField(max_length=1500), blank=True)
    token = JSONField(blank=True)

    # The returned profile data from the last refresh
    profile = JSONField(blank=True)

    # Related Django user (if any)
    def user(self):
        return User.objects.filter(google_oauth_id=self.pk).first()

    @property
    def is_valid(self):
        return timezone.now() < self.expires_at

    def refresh(self):
        pass
