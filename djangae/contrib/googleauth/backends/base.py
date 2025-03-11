"""
    This is duplicated from Django 3.0 to avoid
    starting an import chain that ends up with
    ContentTypes which may not be installed in a
    Djangae project.
"""

import itertools

from ..models import PermissionsMixin, UserPermission, object_id_for_model


class BaseBackend:
    def authenticate(self, request, **kwargs):
        return None

    @classmethod
    def can_authenticate(cls, request):
        """
            This is a pre-check to see if the credentials are
            available to try to authenticate.
        """
        return True

    def get_user(self, user_id):
        return None

    def get_user_permissions(self, user_obj, obj=None):
        """
            Returns a set of permission strings that the user has directly.
            If obj is passed, only returns the permissions for this specific object.
        """
        if isinstance(user_obj, PermissionsMixin):
            if obj is not None:

                obj_id = object_id_for_model(obj)
                object_permissions = UserPermission.objects.filter(
                    user_id=user_obj.pk,
                    obj_id=obj_id,
                ).values_list("permission")

                return set(*object_permissions)
            return user_obj.user_permissions

        return set()

    def get_group_permissions(self, user_obj, obj=None):
        """
            Returns a set of permission strings that the user has directly.
            If obj is passed, only returns the permissions for this specific object.

            TODO: obj permissions, currently returns None instead
        """
        if isinstance(user_obj, PermissionsMixin) and obj is None:
            return set(itertools.chain(*[group.permissions for group in user_obj.groups.all()]))

        return set()

    def get_all_permissions(self, user_obj, obj=None):
        return {
            *self.get_user_permissions(user_obj, obj=obj),
            *self.get_group_permissions(user_obj, obj=obj),
        }

    def has_perm(self, user_obj, perm, obj=None):
        if not user_obj.is_active:
            return False

        return perm in self.get_all_permissions(user_obj, obj=obj)
