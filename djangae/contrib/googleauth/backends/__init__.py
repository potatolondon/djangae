import random
import string
from django.db import (
    connections,
    router,
)
from django.contrib.auth import get_user_model


def _find_atomic_decorator(model):
    connection_name = router.db_for_read(model)
    connection = connections[connection_name]

    # FIXME: When Django GCloud Connectors gets rid of its own atomic decorator
    # the Django atomic() decorator can be used regardless

    if connection.settings_dict['ENGINE'] == 'gcloudc.db.backends.datastore':
        try:
            from gcloudc.db.transaction import atomic
        except ImportError:
            from django.db.transaction import atomic
    else:
        from django.db.transaction import atomic

    return atomic_with_defaults(atomic, using=connection_name)


def atomic_with_defaults(_atomic, **defaults):
    """ Curry the given _atomic decorator to pass the given default kwargs. """
    def atomic(**kwargs):
        final_kwargs = defaults.copy()
        final_kwargs.update(kwargs)
        return _atomic(**final_kwargs)
    return atomic


def _generate_unused_username(ideal):
    """
        Check the database for a user with the specified username
        and return either that ideal username, or an unused generated
        one using the ideal username as a base
    """
    User = get_user_model()

    if not User.objects.filter(username_lower=ideal.lower()).exists():
        return ideal

    exists = True

    # We use random digits rather than anything sequential to avoid any kind of
    # attack vector to get this loop stuck
    while exists:
        random_digits = "".join([random.choice(string.digits) for x in range(5)])
        username = "%s-%s" % (ideal, random_digits)
        exists = User.objects.filter(username_lower=username.lower).exists()

    return username
