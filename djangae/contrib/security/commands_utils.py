import inspect
import re

from django.contrib.admindocs import utils as admindocs_utils
from django.contrib.admindocs import views as admindocs_views
from django.core.exceptions import ViewDoesNotExist
from django.urls.resolvers import URLResolver, URLPattern


def extract_views_from_urlpatterns(urlpatterns, base='', namespace=None, ignored_modules=None):
    """
    Return a list of views from a list of urlpatterns.

    Each object in the returned list is a tuple: (view_func, regex, name)
    """
    ignored_modules = ignored_modules if ignored_modules else []
    views = []

    for p in urlpatterns:

        if isinstance(p, URLPattern):
            # Handle correct single URL patterns
            try:
                if namespace:
                    name = '{0}:{1}'.format(namespace, p.name)
                else:
                    name = p.name
                if hasattr(p.callback, '__module__'):
                    if p.callback.__module__.split('.')[0] not in ignored_modules:
                        views.append((p.callback, base + str(p.pattern), name))
                else:
                    views.append((p.callback, base + str(p.pattern), name))
            except ViewDoesNotExist:
                continue

        elif isinstance(p, URLResolver):
            # Handle include() definitions
            try:
                patterns = p.url_patterns
            except ImportError:
                continue

            views.extend(
                extract_views_from_urlpatterns(
                    patterns, base + str(p.pattern),
                    namespace=(namespace or p.namespace),
                    ignored_modules=ignored_modules
                )
            )

        elif hasattr(p, '_get_callback'):
            # Handle string like 'foo.views.view_name' or just function view
            try:
                views.append((p._get_callback(), base + str(p.pattern), p.name))
            except ViewDoesNotExist:
                continue

        elif hasattr(p, 'url_patterns') or hasattr(p, '_get_url_patterns'):
            # Handle url_patterns objects
            try:
                patterns = p.url_patterns
            except ImportError:
                continue

            views.extend(
                extract_views_from_urlpatterns(
                    patterns, base + str(p.pattern),
                    namespace=namespace, ignored_modules=ignored_modules
                )
            )
        else:
            raise TypeError("%s does not appear to be a urlpattern object" % p)
    return views


def display_as_table(views, headers=('URL', 'Handler path', 'Decorators & Mixins')):
    """
        Get list of views from dumpurls security management command
        and returns them in the form of table to print in command line
    """
    # Find the longest value in each column
    widths = [len(max(columns, key=len)) for columns in zip(*[headers] + sorted(views))]
    widths = [width if width < 100 else 100 for width in widths]
    table_views = []

    table_views.append(
        ' | '.join('{0:<{1}}'.format(title, width) for width, title in zip(widths, headers))
    )
    table_views.append('-+-'.join('-' * width for width in widths))

    for row in views:
        for cell in row:
            if len(cell) > 100:
                cell = cell.split(',')
                cell = [",".join(cell[i:i+2]) for i in range(0, len(cell), 2)]

            mixins = cell
            if isinstance(mixins, list):
                for i, line in enumerate(mixins):
                    cell = line.strip()

        table_views.append(
            ' | '.join('{0:<{1}}'.format(cdata, width) for width, cdata in zip(widths, row))
        )

    return "\n".join([v for v in table_views]) + "\n"


def get_func_name(func):
    if hasattr(func, 'func_name'):
        return func.func_name
    elif hasattr(func, '__name__'):
        return func.__name__
    elif hasattr(func, '__class__'):
        return '%s()' % func.__class__.__name__
    else:
        return re.sub(r' at 0x[0-9a-f]+', '', repr(func))


def get_decorators(func):
    """
        Get function or class and return names of applied decorators.
        Note that due to the dynamic nature of python and the many ways in which functions can be
        decorated, patched or switched, this is - and will only ever be - a best effort attempt.
    """
    decorators = []
    if hasattr(func, '__module__'):
        mod = inspect.getmodule(func)
        source_code = inspect.getsourcelines(mod)[0]
        func_name = get_func_name(func)
        i = 0

        func_def = 'def {}'.format(func_name)
        class_def = 'class {}'.format(func_name)

        for line in source_code:
            if line.startswith(func_def) or line.startswith(class_def):
                j = 1
                k = source_code[i-j]
                # decorators can be defined on the previous line(s), but can have blank lines before them
                # blank lines are '\n', hence we strip() them to see if they're empty
                while k.startswith('@') or not k.strip():
                    if k.startswith('@'):
                        decorators.append(k.strip().split('(')[0])
                    j += 1
                    if j >= i:  # don't wrap around when we get to the start of the file
                        break
                    k = source_code[i-j]
            i += 1

    return decorators


def get_mixins(func, ignored_modules=None):
    """
        Given a Django class-based view, return names and paths to applied mixins
        Has an optional argument for names of modules that should be ignored.
        Note that there could be decorators on the methods of the class (or on methods of the
        mixins), but as with decorators, being sure of finding them all is impossible, so we simply
        list the mixins.
    """
    ignored_modules = ignored_modules if ignored_modules else []
    mixins = []
    # Django class-based views are used by calling .as_view() which creates a nested function that
    # has a 'cls' attribute which is the actual class
    if hasattr(func, 'cls'):
        for klass in func.cls.mro():
            if klass != func.cls and klass.__module__.split('.')[0] not in ignored_modules:
                mixins.append("{}.{}".format(klass.__module__, get_func_name(klass)))

    return mixins


# This is copied from django.contrib.admindocs.views, but improved to deal with non-capturing
# groups within the group.
# TODO: submit this as a patch to Django.

non_named_group_matcher = re.compile(
    r'\('  # opening bracket of group
    '('  # a group for THIS regex...
        r'[^\)]*'  # noqa zero or more characters that are not a closing bracket
        # the next line allows us to have non-capturing groups within the overall group that we're matching
        r'\(\?[^\)]*\)'  # a non-capturing group
        r'[^\)]*'  # zero or more characters that are not a bracket
    ')*'  # all of that ^ bit zero or more times
    r'\)'  # the closing bracket of the group
)


def simplify_regex(pattern):
    """ Do the same as django.contrib.admindocs.views.simplify_regex but with our improved regex.
    """

    original_regex = admindocs_utils.unnamed_group_matcher
    admindocs_utils.unnamed_group_matcher = non_named_group_matcher
    result = admindocs_views.simplify_regex(pattern)
    admindocs_utils.unnamed_group_matcher = original_regex

    return result
