from django.forms import ValidationError
from djangae.contrib.googleauth.models import Group, UserPermission
from djangae.test import TestCase
from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class ObjectWithPermissions(models.Model):
    pass


view_permission = "googleauth.view_objectwithpermissions"


class AnotherObjectWithPermissions(models.Model):
    pass


another_view_permission = "googleauth.view_anotherobjectwithpermissions"


class DefaultPermissionsTest(TestCase):
    def test_user_permission_validated(self):
        user = User.objects.create(
            username='perm_test',
            email='perm_test@example.com',
            password='apassword',
        )

        user.user_permissions.add(view_permission)
        user.clean_fields()
        user.user_permissions.add('invalidapp.view_invalidmodel')

        with self.assertRaises(ValidationError) as err:
            user.clean_fields()

        err.exception.message_dict
        self.assertIn('user_permissions', err.exception.message_dict)

    def test_simple_user_permission(self):
        user = User.objects.create(
            username='perm_test',
            email='perm_test@example.com',
            password='apassword',
        )
        user.user_permissions.add(view_permission)

        self.assertFalse(user.has_perm(another_view_permission))
        self.assertTrue(user.has_perm(view_permission))

    def test_inactive_does_not_have_permissions(self):
        user = User.objects.create(
            email='perm_test@example.com'
        )
        user.user_permissions.add(view_permission)
        user.is_active = False
        user.save()

        self.assertFalse(user.has_perm(view_permission))

    def test_active_superuser_have_all_permissions(self):
        user = User.objects.create(
            email='perm_test@example.com',
            is_superuser=True,
        )

        self.assertTrue(user.has_perm(view_permission))
        self.assertTrue(user.has_perm("create.whatever_you_want"))

        user.is_active = False
        user.save()

        self.assertFalse(user.has_perm(view_permission))
        self.assertFalse(user.has_perm("create.whatever_you_want"))

    def test_group_permission(self):
        user = User.objects.create(
            email='perm_test@example.com'
        )

        test_group = Group.objects.create(name="test_group")
        test_group.permissions.add(view_permission)
        test_group.save()

        user.groups.add(test_group)

        self.assertFalse(user.has_perm(another_view_permission))
        self.assertTrue(user.has_perm(view_permission))

    def test_object_permission(self):
        user = User.objects.create(
            email='perm_test@example.com'
        )

        obj1 = ObjectWithPermissions.objects.create()
        obj2 = ObjectWithPermissions.objects.create()

        UserPermission.objects.create(
            user=user,
            obj=obj1,
            permission=view_permission,
        )

        # User should have permissions for obj1
        self.assertTrue(user.has_perm(view_permission, obj1))

        # but not for all the other models there
        self.assertFalse(user.has_perm(view_permission))

        # nor for a specific one
        self.assertFalse(user.has_perm(view_permission, obj2))

    def test_object_permission_with_same_pk(self):
        user = User.objects.create(
            email='perm_test@example.com'
        )

        obj1 = ObjectWithPermissions.objects.create(pk=1)
        obj2 = AnotherObjectWithPermissions.objects.create(pk=1)

        UserPermission.objects.create(
            user=user,
            obj=obj1,
            permission=view_permission,
        )

        self.assertFalse(user.has_perm(another_view_permission, obj2))

        # Unclear if this is important?
        self.assertFalse(user.has_perm(view_permission, obj2))
