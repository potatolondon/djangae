import django
import logging
import yaml
import os
import datetime
import re
from itertools import chain

from django.core.exceptions import ValidationError
from django.db import models
from django.apps import apps
from django.conf import settings
from django.utils import six

from djangae import environment
from djangae.db.utils import get_top_concrete_parent
from djangae.core.validators import MaxBytesValidator
from djangae.sandbox import allow_mode_write

from google.appengine.api.datastore import (
    Entity,
    Delete,
    Query
)

logger = logging.getLogger(__name__)
_project_special_indexes = {}
_app_special_indexes = {}
_last_loaded_times = {}
_indexes_loaded = False


MAX_COLUMNS_PER_SPECIAL_INDEX = getattr(settings, "DJANGAE_MAX_COLUMNS_PER_SPECIAL_INDEX", 3)
CHARACTERS_PER_COLUMN = [31, 44, 54, 63, 71, 79, 85, 91, 97, 103]
STRIP_PERCENTS = django.VERSION < (1, 10)


def _get_project_index_file():
    project_index_file = os.path.join(environment.get_application_root(), "djangaeidx.yaml")
    return project_index_file


def _get_app_index_files():
    index_files = []

    for app_config in apps.get_app_configs():
        app_path = app_config.path
        project_index_file = os.path.join(app_path, "djangaeidx.yaml")
        index_files.append(project_index_file)
    return index_files


def _get_table_from_model(model_class):
    return model_class._meta.db_table.encode("utf-8")


def _is_iterable(value):
    return hasattr(value, '__iter__')  # is a list, tuple or set?


def _deduplicate_list(value_list):
    """ Deduplicate list of elements; value_list is expected to be a list
    of containing hashable elements. """
    return list(set(value_list))


def _make_lower(value):
    """ Make string and list of strings lowercase """
    if _is_iterable(value):
        return [v.lower() for v in value]
    else:
        return value.lower()


def _merged_indexes():
    """
        Returns the combination of the app and project special indexes
    """
    global _project_special_indexes
    global _app_special_indexes

    result = _app_special_indexes.copy()
    for model, indexes in _project_special_indexes.items():
        for field_name, values in indexes.items():
            result.setdefault(
                model, {}
            ).setdefault(field_name, []).extend(values)
    return result


def load_special_indexes():
    global _project_special_indexes
    global _app_special_indexes
    global _last_loaded_times
    global _indexes_loaded

    if _indexes_loaded and environment.is_production_environment():
        # Index files can't change if we're on production, so once they're loaded we don't need
        # to check their modified times and reload them
        return

    def _read_file(filepath):
        # Load any existing indexes
        with open(filepath, "r") as stream:
            data = yaml.safe_load(stream)
        return data

    project_index_file = _get_project_index_file()
    app_files = _get_app_index_files()

    files_to_reload = {}

    # Go through and reload any files that we find
    for file_path in [project_index_file] + app_files:
        if not os.path.exists(file_path):
            continue

        mtime = os.path.getmtime(file_path)
        if _last_loaded_times.get(file_path) and _last_loaded_times[file_path] == mtime:
            # The file hasn't changed since last time, so do nothing
            continue
        else:
            # Mark this file for reloading, store the current modified time
            files_to_reload[file_path] = mtime

    # First, reload the project index file,
    if project_index_file in files_to_reload:
        mtime = files_to_reload[project_index_file]
        _project_special_indexes = _read_file(project_index_file)
        _last_loaded_times[project_index_file] = mtime

        # Remove it from the files to reload
        del files_to_reload[project_index_file]

    # Now, load the rest of the files and update any entries
    for file_path in files_to_reload:
        mtime = files_to_reload[project_index_file]
        new_data = _read_file(file_path)
        _last_loaded_times[file_path] = mtime

        # Update the app special indexes list
        for model, indexes in new_data.items():
            for field_name, values in indexes.items():
                _app_special_indexes.setdefault(
                    model, {}
                ).setdefault(field_name, []).extend(values)

    _indexes_loaded = True
    logger.debug("Loaded special indexes for %d models", len(_merged_indexes()))


def special_index_exists(model_class, field_name, index_type):
    table = _get_table_from_model(model_class)
    return index_type in _merged_indexes().get(table, {}).get(field_name, [])


def special_indexes_for_model(model_class):
    classes = [model_class] + model_class._meta.parents.keys()

    result = {}
    for klass in classes:
        result.update(_merged_indexes().get(_get_table_from_model(klass), {}))
    return result


def special_indexes_for_column(model_class, column):
    return special_indexes_for_model(model_class).get(column, [])


def write_special_indexes():
    """
        Writes the project-specific indexes to the project djangaeidx.yaml
    """
    project_index_file = _get_project_index_file()

    with allow_mode_write():
        with open(project_index_file, "w") as stream:
            stream.write(yaml.dump(_project_special_indexes))


def add_special_index(model_class, field_name, indexer, operator, value=None):
    from djangae.utils import in_testing
    from django.conf import settings

    index_type = indexer.prepare_index_type(operator, value)

    field_name = field_name.encode("utf-8")  # Make sure we are working with strings

    load_special_indexes()

    if special_index_exists(model_class, field_name, index_type):
        return

    if environment.is_production_environment() or (
        in_testing() and not getattr(settings, "GENERATE_SPECIAL_INDEXES_DURING_TESTING", False)
    ):
        raise RuntimeError(
            "There is a missing index in your djangaeidx.yaml - \n\n{0}:\n\t{1}: [{2}]".format(
                _get_table_from_model(model_class), field_name, index_type
            )
        )

    _project_special_indexes.setdefault(
        _get_table_from_model(model_class), {}
    ).setdefault(field_name, []).append(str(index_type))

    write_special_indexes()


class IgnoreForIndexing(Exception):
    """
        An exception thrown from prep_value_for_database if the index column
        should be removed from the entity.

        Frustratingly, the legacy icontains and contains Indexers use 'value' when
        determining the column name, and so you must pass the prepared value for the
        column anyway, even though it won't be used.

        When the legacy icontains/contains indexers are removed we should:

         - Remove __init__ from this class
         - Remove 'value' as an argument to indexed_column_name
         - Stop setting 'values' from processed_value in django_instance_to_entity
    """

    def __init__(self, processed_value):
        self.processed_value = processed_value


class Indexer(object):
    # Set this to True if prep_value_for_database returns additional Entity instances
    # to save as descendents, rather than values to index as columns
    PREP_VALUE_RETURNS_ENTITIES = False

    # **IMPORTANT! If you return Entities from an indexer, the kind *must* start with
    # _djangae_idx_XXXX where XXX is the top concrete model kind of the instance you
    # are indexing. If you do not do this, then the tables will not be correctly flushed
    # when the database is flushed**

    @classmethod
    def cleanup(cls, datastore_key):
        """
            Called when an instance is deleted, if the instances has an index
            which uses this indexer. This is mainly for cleaning up descendent kinds
            (e.g. like those used in contains + icontains)
        """
        pass

    def handles(self, field, operator):
        """
            When given a field instance and an operator (e.g. gt, month__gt etc.)
            returns True or False whether or not this is the indexer to handle that
            situation
        """
        raise NotImplementedError()

    def validate_can_be_indexed(self, value, negated):
        """Return True if the value is indexable, False otherwise"""
        raise NotImplementedError()

    def prep_value_for_database(self, value, index, **kwargs): raise NotImplementedError()
    def prep_value_for_query(self, value, **kwargs): raise NotImplementedError()
    def indexed_column_name(self, field_column, value, index): raise NotImplementedError()
    def prep_query_operator(self, op):
        if "__" in op:
            return op.split("__")[-1]
        else:
            return "exact"  # By default do an exact operation

    def prepare_index_type(self, index_type, value): return index_type

    def unescape(self, value):
        value = value.replace("\\_", "_")
        value = value.replace("\\%", "%")
        value = value.replace("\\\\", "\\")
        return value


class StringIndexerMixin(object):
    STRING_FIELDS = (
        models.TextField,
        models.CharField,
        models.URLField,
        models.DateTimeField, # Django allows these for some reason
        models.DateField,
        models.TimeField,
        models.IntegerField, # SQL coerces ints to strings, and so we need these too
        models.PositiveIntegerField,
        models.AutoField
    )

    def handles(self, field, operator):
        from djangae.fields import iterable
        try:
            # Make sure the operator is in there
            operator.split("__").index(self.OPERATOR)
        except ValueError:
            return False

        if isinstance(field, self.STRING_FIELDS):
            return True
        elif (
            isinstance(field, (iterable.ListField, iterable.SetField)) and
            field.item_field_type.__class__ in self.STRING_FIELDS and operator.startswith("item__")
        ):
            return True
        return False


class DateIndexerMixin(object):
    def handles(self, field, operator):
        from djangae.fields import iterable
        DATE_FIELDS = (
            models.DateField,
            models.DateTimeField
        )

        if operator.split("__")[0] != self.OPERATOR:
            return False

        if isinstance(field, DATE_FIELDS):
            return True
        elif (
            isinstance(field, (iterable.ListField, iterable.SetField)) and
            field.item_field_type.__class__ in DATE_FIELDS and operator.startswith("item__")
        ):
            return True

        return False


class TimeIndexerMixin(object):
    def handles(self, field, operator):
        from djangae.fields import iterable

        TIME_FIELDS = (
            models.TimeField,
            models.DateTimeField
        )

        if operator.split("__")[0] != self.OPERATOR:
            return False

        if isinstance(field, TIME_FIELDS):
            return True
        elif (
            isinstance(field, (iterable.ListField, iterable.SetField)) and
            field.item_field_type.__class__ in TIME_FIELDS and operator.startswith("item__")
        ):
            return True

        return False

class IExactIndexer(StringIndexerMixin, Indexer):
    OPERATOR = 'iexact'

    def validate_can_be_indexed(self, value, negated):
        return len(value) < 500

    def prep_value_for_database(self, value, index, **kwargs):
        if value is None:
            return None

        if isinstance(value, (int, long)):
            value = str(value)
        return value.lower()

    def prep_value_for_query(self, value, **kwargs):
        value = self.unescape(value)
        return value.lower()

    def indexed_column_name(self, field_column, value, index):
        return "_idx_iexact_{0}".format(field_column)


class HourIndexer(TimeIndexerMixin, Indexer):
    OPERATOR = 'hour'

    def validate_can_be_indexed(self, value, negated):
        return isinstance(value, datetime.datetime)

    def prep_value_for_database(self, value, index, **kwargs):
        if value:
            return value.hour
        return None

    def prep_value_for_query(self, value, **kwargs):
        if isinstance(value, (int, long)):
            return value

        if isinstance(value, six.string_types):
            value = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value.hour

    def indexed_column_name(self, field_column, value, index):
        return "_idx_hour_{0}".format(field_column)


class MinuteIndexer(TimeIndexerMixin, Indexer):
    OPERATOR = 'minute'

    def validate_can_be_indexed(self, value, negated):
        return isinstance(value, datetime.datetime)

    def prep_value_for_database(self, value, index, **kwargs):
        if value:
            return value.minute
        return None

    def prep_value_for_query(self, value, **kwargs):
        if isinstance(value, (int, long)):
            return value

        if isinstance(value, six.string_types):
            value = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value.minute

    def indexed_column_name(self, field_column, value, index):
        return "_idx_minute_{0}".format(field_column)


class SecondIndexer(TimeIndexerMixin, Indexer):
    OPERATOR = 'second'
    def validate_can_be_indexed(self, value, negated):
        return isinstance(value, datetime.datetime)

    def prep_value_for_database(self, value, index, **kwargs):
        if value:
            return value.second
        return None

    def prep_value_for_query(self, value, **kwargs):
        if isinstance(value, (int, long)):
            return value

        if isinstance(value, six.string_types):
            value = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value.second

    def indexed_column_name(self, field_column, value, index):
        return "_idx_second_{0}".format(field_column)


class DayIndexer(DateIndexerMixin, Indexer):
    OPERATOR = 'day'

    def validate_can_be_indexed(self, value, negated):
        return isinstance(value, (datetime.datetime, datetime.date))

    def prep_value_for_database(self, value, index, **kwargs):
        if value:
            return value.day
        return None

    def prep_value_for_query(self, value, **kwargs):
        if isinstance(value, (int, long)):
            return value

        if isinstance(value, six.string_types):
            value = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value.day

    def indexed_column_name(self, field_column, value, index):
        return "_idx_day_{0}".format(field_column)


class YearIndexer(DateIndexerMixin, Indexer):
    OPERATOR = 'year'

    def validate_can_be_indexed(self, value, negated):
        return isinstance(value, (datetime.datetime, datetime.date))

    def prep_value_for_database(self, value, index, **kwargs):
        if value:
            return value.year
        return None

    def prep_value_for_query(self, value, **kwargs):
        if isinstance(value, (int, long)):
            return value

        if isinstance(value, six.string_types):
            value = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

        return value.year

    def indexed_column_name(self, field_column, value, index):
        return "_idx_year_{0}".format(field_column)


class MonthIndexer(DateIndexerMixin, Indexer):
    OPERATOR = 'month'

    def validate_can_be_indexed(self, value, negated):
        return isinstance(value, (datetime.datetime, datetime.date))

    def prep_value_for_database(self, value, index, **kwargs):
        if value:
            return value.month
        return None

    def prep_value_for_query(self, value, **kwargs):
        if isinstance(value, (int, long)):
            return value

        if isinstance(value, six.string_types):
            value = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

        return value.month

    def indexed_column_name(self, field_column, value, index):
        return "_idx_month_{0}".format(field_column)


class WeekDayIndexer(DateIndexerMixin, Indexer):
    OPERATOR = 'week_day'

    def validate_can_be_indexed(self, value, negated):
        return isinstance(value, (datetime.datetime, datetime.date))

    def prep_value_for_database(self, value, index, **kwargs):
        if value:
            zero_based_weekday = value.weekday()
            if zero_based_weekday == 6:  # Sunday
                return 1  # Django treats the week as starting at Sunday, but 1 based
            else:
                return zero_based_weekday + 2

        return None

    def prep_value_for_query(self, value, **kwargs):
        return value

    def indexed_column_name(self, field_column, value, index):
        return "_idx_week_day_{0}".format(field_column)


class ContainsIndexer(StringIndexerMixin, Indexer):
    PREP_VALUE_RETURNS_ENTITIES = True
    OPERATOR = u'contains'
    INDEXED_COLUMN_NAME = OPERATOR

    def validate_can_be_indexed(self, value, negated):
        if negated:
            return False

        try:
            MaxBytesValidator(limit_value=1500)(value)
            return True
        except ValidationError:
            return False

    @classmethod
    def cleanup(cls, datastore_key):

        # Kindless query, we don't know the kinds because we don't know all the fields
        # that use contains. But, we do know that all the things we need to delete are:
        # a.) A descendent
        # b.) Have a key name of whatever OPERATOR is

        qry = Query(keys_only=True, namespace=datastore_key.namespace())
        qry = qry.Ancestor(datastore_key)

        # Delete all the entities matching the ancestor query
        Delete([x for x in qry.Run() if x.name() == cls.OPERATOR])


    def _generate_kind_name(self, model, column):
        return "_djangae_idx_{}_{}".format(
            get_top_concrete_parent(model)._meta.db_table,
            column
        )

    def _generate_permutations(self, value):
        return [value[i:] for i in range(len(value))]

    def prep_value_for_database(self, value, index, model, column):
        if value is None:
            raise IgnoreForIndexing([])

        # If this a date or a datetime, or something that supports isoformat, then use that
        if hasattr(value, "isoformat"):
            value = value.isoformat()

        if _is_iterable(value):
            value = list(chain(*[self._generate_permutations(v) for v in value]))
        else:
            value = self._generate_permutations(value)

        if not value:
            raise IgnoreForIndexing([])

        value = list(set(value)) # De-duplicate

        entity = Entity(self._generate_kind_name(model, column), name=self.OPERATOR)
        entity[self.INDEXED_COLUMN_NAME] = value
        return [entity]

    def prep_query_operator(self, operator):
        return "IN"

    def indexed_column_name(self, field_column, value, index):
        # prep_value_for_query returns a list PKs, so we return __key__ as the column
        return "__key__"

    def prep_value_for_query(self, value, model, column, connection):
        """
            Return a list of IDs of the associated contains models, these should
            match up with the IDs from the parent entities
        """

        if hasattr(value, "isoformat"):
            value = value.isoformat()
        else:
            value = unicode(value)
        value = self.unescape(value)

        if STRIP_PERCENTS:
            # SQL does __contains by doing LIKE %value%
            if value.startswith("%") and value.endswith("%"):
                value = value[1:-1]

        namespace = connection.settings_dict.get("NAMESPACE", "")
        qry = Query(self._generate_kind_name(model, column), keys_only=True, namespace=namespace)
        qry['{} >='.format(self.INDEXED_COLUMN_NAME)] = value
        qry['{} <='.format(self.INDEXED_COLUMN_NAME)] = value + u'\ufffd'

        # We can't filter on the 'name' as part of the query, because the name is the key and these
        # are child entities of the ancestor entities which they are indexing, and as we don't know
        # the keys of the ancestor entities we can't create the complete keys, hence the comparison
        # of `x.name() == self.OPERATOR` happens here in python
        resulting_keys = set([x.parent() for x in qry.Run() if x.name() == self.OPERATOR])
        return resulting_keys


class IContainsIndexer(ContainsIndexer):
    OPERATOR = 'icontains'

    def _generate_permutations(self, value):
        return super(IContainsIndexer, self)._generate_permutations(value.lower())

    def prep_value_for_query(self, value, model, column, connection):
        return super(IContainsIndexer, self).prep_value_for_query(value.lower(), model, column, connection)


class LegacyContainsIndexer(StringIndexerMixin, Indexer):
    OPERATOR = 'contains'

    def number_of_permutations(self, value):
        return sum(range(len(value)+1))

    def validate_can_be_indexed(self, value, negated):
        if negated:
            return False
        return isinstance(value, six.string_types) and len(value) <= 500

    def prep_value_for_database(self, value, index, **kwargs):
        results = []
        if value:
            # If this a date or a datetime, or something that supports isoformat, then use that
            if hasattr(value, "isoformat"):
                value = value.isoformat()

            if self.number_of_permutations(value) > MAX_COLUMNS_PER_SPECIAL_INDEX*500:
                raise ValueError(
                    "Can't index for contains query, this value is too long and has too many "
                    "permutations. You can increase the DJANGAE_MAX_COLUMNS_PER_SPECIAL_INDEX "
                    "setting to fix that. Use with caution."
                )
            if len(value) > CHARACTERS_PER_COLUMN[-1]:
                raise ValueError(
                    "Can't index for contains query, this value can be maximum {0} characters long."
                    .format(CHARACTERS_PER_COLUMN[-1])
                )

            if _is_iterable(value):
                # `value` is a list of strings. Generate a single combined list containing the
                # substrings of each string in `value`
                for element in value:
                    length = len(element)
                    lists = [element[i:j + 1] for i in range(length) for j in range(i, length)]
                    results.extend(lists)
            else:
                # `value` is a string. Generate a list of all its substrings.
                length = len(value)
                lists = [value[i:j + 1] for i in range(length) for j in range(i, length)]
                results.extend(lists)

        if not results:
            raise IgnoreForIndexing([])

        return _deduplicate_list(results)

    def prep_value_for_query(self, value, **kwargs):
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        else:
            value = unicode(value)
        value = self.unescape(value)

        if STRIP_PERCENTS:
            # SQL does __contains by doing LIKE %value%
            if value.startswith("%") and value.endswith("%"):
                value = value[1:-1]

        return value

    def indexed_column_name(self, field_column, value, index):
        # This we use when we actually query to return the right field for a given
        # value length
        length = len(value)

        column_number = 0
        for x in CHARACTERS_PER_COLUMN:
            if length > x:
                column_number += 1
        return "_idx_contains_{0}_{1}".format(field_column, column_number)

    def prep_query_operator(self, op):
        return "exact"


class LegacyIContainsIndexer(LegacyContainsIndexer):
    OPERATOR = 'icontains'

    def prep_value_for_database(self, value, index, **kwargs):
        if value is None:
            raise IgnoreForIndexing("")
        value = _make_lower(value)
        result = super(LegacyIContainsIndexer, self).prep_value_for_database(value, index)
        return result if result else None

    def indexed_column_name(self, field_column, value, index):
        column_name = super(LegacyIContainsIndexer, self).indexed_column_name(field_column, value, index)
        return column_name.replace('_idx_contains_', '_idx_icontains_')

    def prep_value_for_query(self, value, **kwargs):
        return super(LegacyIContainsIndexer, self).prep_value_for_query(value).lower()


class EndsWithIndexer(StringIndexerMixin, Indexer):
    """
        dbindexer originally reversed the string and did a startswith on it.
        However, this is problematic as it uses an inequality and therefore
        limits the queries you can perform. Instead, we store all permutations
        of the last characters in a list field. Then we can just do an exact lookup on
        the value. Which isn't as nice, but is more flexible.
    """
    OPERATOR = 'endswith'

    def validate_can_be_indexed(self, value, negated):
        if negated:
            return False

        return isinstance(value, six.string_types) and len(value) < 500

    def prep_value_for_database(self, value, index, **kwargs):
        if value is None:
            return None

        results = []
        if _is_iterable(value):
            # `value` is a list of strings. Create a single combined list of "endswith" values
            # of all the strings in the list
            for element in value:
                for i in range(0, len(element)):
                    results.append(element[i:])
        else:
            # `value` is a string. Create a list of "endswith" strings.
            for i in range(0, len(value)):
                results.append(value[i:])

        if not results:
            return None

        return _deduplicate_list(results)

    def prep_value_for_query(self, value, **kwargs):
        value = self.unescape(value)
        if STRIP_PERCENTS:
            if value.startswith("%"):
                value = value[1:]
        return value

    def indexed_column_name(self, field_column, value, index):
        return "_idx_endswith_{0}".format(field_column)

    def prep_query_operator(self, op):
        return "exact"


class IEndsWithIndexer(EndsWithIndexer):
    """
        Same as above, just all lower cased
    """
    OPERATOR = 'iendswith'

    def prep_value_for_database(self, value, index, **kwargs):
        if value:
            value = _make_lower(value)
        return super(IEndsWithIndexer, self).prep_value_for_database(value, index)

    def prep_value_for_query(self, value, **kwargs):
        return super(IEndsWithIndexer, self).prep_value_for_query(value.lower())

    def indexed_column_name(self, field_column, value, index):
        return "_idx_iendswith_{0}".format(field_column)


class StartsWithIndexer(StringIndexerMixin, Indexer):
    """
        Although we can do a startswith natively, doing it this way allows us to
        use more queries (E.g. we save an exclude)
    """
    OPERATOR = 'startswith'

    def validate_can_be_indexed(self, value, negated):
        if negated:
            return False

        return isinstance(value, six.string_types) and len(value) < 500

    def prep_value_for_database(self, value, index, **kwargs):
        if value is None:
            return None

        if isinstance(value, datetime.datetime):
            value = value.strftime("%Y-%m-%d %H:%M:%S")

        results = []
        if _is_iterable(value):
            # `value` is a list of strings. Create a single combined list of "startswith" values
            # of all the strings in the list
            for element in value:
                for i in range(1, len(element) + 1):
                    results.append(element[:i])
        else:
            # `value` is a string. Create a list of "startswith" strings.
            for i in range(1, len(value) + 1):
                results.append(value[:i])

        if not results:
            return None

        return _deduplicate_list(results)

    def prep_value_for_query(self, value, **kwargs):
        value = self.unescape(value)
        if STRIP_PERCENTS:
            if value.endswith("%"):
                value = value[:-1]
        return value

    def indexed_column_name(self, field_column, value, index):
        return "_idx_startswith_{0}".format(field_column)

    def prep_query_operator(self, op):
        return "exact"


class IStartsWithIndexer(StartsWithIndexer):
    """
        Same as above, just all lower cased
    """
    OPERATOR = 'istartswith'

    def prep_value_for_database(self, value, index, **kwargs):
        if value:
            value = _make_lower(value)
        return super(IStartsWithIndexer, self).prep_value_for_database(value, index)

    def prep_value_for_query(self, value, **kwargs):
        return super(IStartsWithIndexer, self).prep_value_for_query(value.lower())

    def indexed_column_name(self, field_column, value, index):
        return "_idx_istartswith_{0}".format(field_column)


class RegexIndexer(StringIndexerMixin, Indexer):
    OPERATOR = 'regex'

    def prepare_index_type(self, index_type, value):
        """
            If we're dealing with RegexIndexer, we create a new index for each
            regex pattern. Indexes are called regex__pattern.
        """
        return '{}__{}'.format(index_type, value.encode("utf-8").encode('hex'))

    def validate_can_be_indexed(self, value, negated):
        if negated:
            return False

        return isinstance(value, bool)

    def get_pattern(self, index):
        try:
            return index.split('__')[-1].decode('hex').decode("utf-8")
        except IndexError:
            return ''

    def check_if_match(self, value, index, flags=0):
        pattern = self.get_pattern(index)

        if value:
            if _is_iterable(value):
                if any([bool(re.search(pattern, x, flags)) for x in value]):
                    return True
            else:
                if isinstance(value, (int, long)):
                    value = str(value)

                return bool(re.search(pattern, value, flags))
        return False

    def prep_value_for_database(self, value, index, **kwargs):
        return self.check_if_match(value, index)

    def prep_value_for_query(self, value, **kwargs):
        return True

    def indexed_column_name(self, field_column, value, index):
        return "_idx_regex_{0}_{1}".format(
            field_column, self.get_pattern(index).encode("utf-8").encode('hex')
        )

    def prep_query_operator(self, op):
        return "exact"


class IRegexIndexer(RegexIndexer):
    OPERATOR = 'iregex'

    def prepare_index_type(self, index_type, value):
        return '{}__{}'.format(index_type, value.encode('hex'))

    def prep_value_for_database(self, value, index, **kwargs):
        return self.check_if_match(value, index, flags=re.IGNORECASE)

    def indexed_column_name(self, field_column, value, index):
        return "_idx_iregex_{0}_{1}".format(field_column, self.get_pattern(index).encode('hex'))


_REGISTERED_INDEXERS = []

def register_indexer(indexer_class):
    global _REGISTERED_INDEXERS
    _REGISTERED_INDEXERS.append(indexer_class())


def get_indexer(field, operator):
    global _REGISTERED_INDEXERS

    for indexer in _REGISTERED_INDEXERS:
        if indexer.handles(field, operator):
            return indexer

def indexers_for_model(model_class):
    indexes = special_indexes_for_model(model_class)

    indexers = []
    for field in model_class._meta.fields:
        if field.name in indexes:
            for operator in indexes[field.name]:
                indexers.append(get_indexer(field, operator))
    return set(indexers)


register_indexer(IExactIndexer)

if getattr(settings, "DJANGAE_USE_LEGACY_CONTAINS_LOGIC", False):
    register_indexer(LegacyContainsIndexer)
    register_indexer(LegacyIContainsIndexer)
else:
    register_indexer(ContainsIndexer)
    register_indexer(IContainsIndexer)

register_indexer(HourIndexer)
register_indexer(MinuteIndexer)
register_indexer(SecondIndexer)
register_indexer(DayIndexer)
register_indexer(MonthIndexer)
register_indexer(YearIndexer)
register_indexer(WeekDayIndexer)
register_indexer(EndsWithIndexer)
register_indexer(IEndsWithIndexer)
register_indexer(StartsWithIndexer)
register_indexer(IStartsWithIndexer)
register_indexer(RegexIndexer)
register_indexer(IRegexIndexer)

