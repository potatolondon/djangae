from django.forms import ValidationError
from django.apps import apps
from django.conf import settings
from django.db import models

CUSTOM_PERMISSIONS = getattr(settings, "GOOGLEAUTH_CUSTOM_PERMISSIONS", {})

ALL_PERMISSIONS = []


def get_permission_choices():
    """
        Returns a list of permissions that can be set
        for users. Defaults are the same as Django
        (https://docs.djangoproject.com/en/3.0/topics/auth/default/#default-permissions)
    """

    if len(ALL_PERMISSIONS) == 0:
        DEFAULT_PERMISSIONS = ("add", "change", "delete", "view")
        GLOBAL_PERMISSIONS = tuple(
            list(DEFAULT_PERMISSIONS) + list(CUSTOM_PERMISSIONS.get('__all__', []))
        )

        result = []

        for app in apps.get_app_configs():
            for model in app.get_models():
                model_name = model.__name__
                app_model = "%s.%s" % (model._meta.app_label, model_name)

                codenames = list(GLOBAL_PERMISSIONS) + list(CUSTOM_PERMISSIONS.get(app_model, []))

                for permission in codenames:
                    result.append(
                        (
                            "%s.%s_%s" % (
                                model._meta.app_label,
                                permission,
                                model_name.lower()
                            ),
                            "Can %s %s.%s" % (permission, model._meta.app_label, model_name)
                        )
                    )

        ALL_PERMISSIONS.extend(result)
    return ALL_PERMISSIONS


def _permission_choice_validator(choice):
    if choice is not None:
        if choice not in [value for value, _ in get_permission_choices()]:
            raise ValidationError(
                f"'{choice}' is not a valid permission.",
            )


class PermissionChoiceField(models.CharField):
    def __init__(self, *args, **kwargs):
        kwargs["max_length"] = 150
        validators = kwargs.pop("validators", [])
        validators.append(_permission_choice_validator)
        kwargs["validators"] = validators
        super().__init__(self, *args, **kwargs)

    def deconstruct(self):
        # Note, we do not call super() because that evaluates the choices when we don't
        # need to and in some cases that causes a recursion error (presumably because we access apps)

        name = self.name
        path = "%s.%s" % (self.__class__.__module__, self.__class__.__qualname__)
        args = []
        kwargs = {}

        return name, path, args, kwargs
