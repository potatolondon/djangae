# Sleuth - a Simple mocking library

# USAGE:

#  Watch calls with sleuth.watch
#
#  with sleuth.watch("some.path.to.thing") as mock:
#      thing(1, a=2)
#      self.assertTrue(mock.called)
#      self.assertEqual(1, mock.call_count)
#      self.assertEqual([((1,), {a:2})], mock.calls)
#
#  Replace functions with sleuth.switch...
#
#  with sleuth.switch("some.path.to.thing", lambda x: pass) as mock:
#

import time
import functools
import collections


def _dot_lookup(thing, comp, import_path):
    try:
        return getattr(thing, comp)
    except AttributeError:
        __import__(import_path)
        return getattr(thing, comp)


def _evaluate_path(target):
    components = target.split('.')
    import_path = components.pop(0)
    thing = __import__(import_path)

    for comp in components:
        import_path += ".%s" % comp
        thing = _dot_lookup(thing, comp, import_path)
    return thing


def _patch(path, replacement):
    thing = _evaluate_path(
        ".".join(path.split(".")[:-1])
    )

    setattr(thing, path.split(".")[-1], replacement)


class ContextDecorator(object):
    def __call__(self, func):
        @functools.wraps(func)
        def _wrapped(*args, **kwargs):
            with self:
                return func(*args, **kwargs)
        return _wrapped


Args = collections.namedtuple('Args', ('args', 'kwargs'))


class Watch(ContextDecorator):
    """
        A context manager that is used to watch a function for calls. It essentially decorates
        the function for the lifetime of the context and records all the calls made to it so that
        you can test that everything is as you expect it to be
    """
    def __init__(self, func_path):
        self._original_func = _evaluate_path(func_path)
        self._func_path = func_path

        if not hasattr(self._original_func, "__call__"):
            raise TypeError("Tried to watch something that isn't a callable")

        def wrapper(_func):
            def wrapped(*args, **kwargs):
                wrapped.call_count += 1
                wrapped.calls.append(
                    Args(args, kwargs)
                )
                wrapped.called = True
                wrapped.call_times.append(time.time())
                ret_val = _func(*args, **kwargs)
                wrapped.call_returns.append(ret_val)
                return ret_val

            wrapped.call_count = 0
            wrapped.calls = []
            wrapped.called = False
            wrapped.call_times = []
            wrapped.call_returns = []

            return wrapped

        self._mock = wrapper(self._original_func)

    def __enter__(self):
        _patch(self._func_path, self._mock)

        return self._mock

    def __exit__(self, *args, **kwargs):
        _patch(self._func_path, self._original_func)


watch = Watch


class Switch(ContextDecorator):
    """
        Replaces a function specified by a path, with the passed callable. If the passed in
        replacement is callable then it is wrapped using the above Watch context manager so that
        you can also assert that your replacement is called as you expect.
    """
    def __init__(self, func_path, replacement):
        self._original_func = _evaluate_path(func_path)
        self._func_path = func_path
        self._replacement = replacement

        # If the original thing we're replacing is a property, make sure
        # we make the replacement thing a property too
        if isinstance(self._original_func, property):
            self._replacement = property(self._replacement)

        self._watch = None

    def __enter__(self):
        _patch(self._func_path, self._replacement)
        if callable(self._replacement):
            self._watch = watch(self._func_path)
            return self._watch.__enter__()

    def __exit__(self, *args, **kwargs):
        if self._watch:
            self._watch.__exit__(*args, **kwargs)
        _patch(self._func_path, self._original_func)


switch = Switch


class Emplace(ContextDecorator):
    """
        Given a list or dictionary, this will temporarily replace the
        contents without changing the object reference itself.
    """
    def __init__(self, obj_path, replacement_values, clear=False):
        self._clear = clear
        self._target = _evaluate_path(obj_path)
        self._original_values = None
        assert (isinstance(self._target, (list, dict)))

        self._replacement_values = replacement_values

    def __enter__(self):
        if isinstance(self._target, dict):
            self._original_values = self._target.copy()
            if self._clear:
                self._target.clear()
            self._target.update(self._replacement_values)
        else:
            self._original_values = self._target[:]
            if self._clear:
                self._target[:] = self._replacement_values
            else:
                self._target.extend(self._replacement_values)

    def __exit__(self, *args, **kwargs):
        if isinstance(self._target, dict):
            self._target.clear()
            self._target.update(self._original_values)
        else:
            self._target[:] = self._original_values


emplace = Emplace


class Detonate(Switch):
    def __init__(self, func_path, exception=None):
        self._exception = exception or Exception

        def throw(*args, **kwargs):
            if callable(self._exception):
                raise self._exception("Detonated %s" % func_path)
            else:
                raise self._exception

        super(Detonate, self).__init__(func_path, throw)


detonate = Detonate


class Fake(Switch):
    def __init__(self, func_path, return_value):
        def replacement(*args, **kwargs):
            return return_value

        super(Fake, self).__init__(func_path, replacement)


fake = Fake
