from math import ceil
from typing import Callable
import logging
import uuid

from django.db.models.query import QuerySet

FIRESTORE_MAX_INT = 2 ** 63 - 1
# https://github.com/firebase/firebase-js-sdk/blob/4f446f0a1c00f080fb58451b086efa899be97a08/packages/firestore/src/util/misc.ts#L24-L34
FIRESTORE_KEY_NAME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
FIRESTORE_KEY_NAME_LENGTH = 20
FIREBASE_UID_LENGTH = 28

logger = logging.getLogger(__name__)


def _find_random_keys(queryset: QuerySet, shard_count: int) -> list:
    try:
        # This gets moved in gcloudc as part of the Firestore backend implementation
        from gcloudc.db.backends.datastore.expressions import Scatter
    except ImportError:
        from gcloudc.db.backends.common.expressions import Scatter

    OVERSAMPLING_FACTOR = 32

    return list(
        queryset.model.objects.order_by(Scatter()).values_list("pk", flat=True)[
            :(shard_count * OVERSAMPLING_FACTOR)
        ]
    )


def sequential_int_key_ranges(queryset, shard_count):
    """
        Given a queryset and a number of shards.
        This function generate key-ranges for a model with
        an integer, dense, sequential primary key, which is usually the default
        when using a SQL backend with autogenerated pks.
    """
    qs = queryset.order_by("pk").values_list("pk", flat=True)
    smallest = qs.first()
    biggest = qs.last()
    max_gap = biggest - smallest
    size = ceil(max_gap / shard_count)
    if biggest < shard_count:
        shard_count = max_gap
        size = 1

    current_min = smallest
    current_max = smallest + size
    key_ranges = [(current_min, current_max)]

    while current_max < biggest:
        current_min += size
        current_max += size
        key_ranges.append((current_min, current_max))

    # If biggest/shard is a whole number, we'd lose the last element (otherwise "ceil" will fix it)
    # e.g. 1000/10 = 100, last range would be (900, 1000), which is off by one
    key_ranges[-1] = (biggest - size, biggest + 1)
    return key_ranges


def datastore_key_ranges(
    queryset: QuerySet,
    shard_count: int,
    random_keys_getter: Callable[[QuerySet, int], list] = _find_random_keys,
) -> list:
    """
        Given a queryset and a number of shard. This function makes use of the
        __scatter__ property to return a list of key ranges for sharded iteration.

        `random_keys_getter` is a callable used to generate random keys.
        It defaults to `_find_random_keys`, but can be used to customise how random keys are
        generated for a given model, e.g. `_find_random_keys` uses the `objects` model manager,
        other implementations can use a different model manager.
        This is especially useful on AppEngine Python 3 which no longer allows `__scatter__` indexes.
    """

    if shard_count > 1:
        # Use the scatter property to generate shard points
        random_keys = random_keys_getter(queryset, shard_count)

        if not random_keys:
            # No random keys? Don't shard
            key_ranges = [(None, None)]
        else:
            random_keys.sort()

            # We have enough random keys to shard things
            if len(random_keys) >= shard_count:
                index_stride = len(random_keys) / float(shard_count)
                split_keys = [random_keys[int(round(index_stride * i))] for i in range(1, shard_count)]
            else:
                split_keys = random_keys

            key_ranges = [(None, split_keys[0])] + [
                (split_keys[i], split_keys[i + 1]) for i in range(len(split_keys) - 1)
            ] + [(split_keys[-1], None)]
    else:
        # Don't shard
        key_ranges = [(None, None)]

    return key_ranges


class SampledKeyRangeGenerator:
    """ A pickleable callable to be passed as the `key_ranges_getter` kwarg to Djangae's
        `defer_iteration_with_finalize`. It will create a set of key ranges based on a field whose
        values might be unevenly clustered (meaning that using evenly-spaced ranges  would result in
        a few of the ranges doing the bulk of the work).
    """

    def __init__(self, queryset, sharding_field, sample_size=1000, using=None):
        """ The queryset should be ordered in such a way that fetching the first `sample_size`
            objects from it will give a good representation of how the `sharding_field` values are
            distributed/clustered. This queryset should be ordered by something different to the
            one passed to __call__ - i.e. your first queryset is ordered by field A in order to find
            the distribution of field B which is used to shard the second queryset for processing.
        """
        self.using = using
        self.model = queryset.model
        self.query = queryset.query
        self.sharding_field = sharding_field
        self.sample_size = sample_size

    def __call__(self, queryset, shard_count: int, *args, **kwargs):
        split_points = self._get_split_points(shard_count)
        if split_points:
            ranges = []
            previous_split_point = None
            for split_point in split_points:
                ranges.append([previous_split_point, split_point])
                previous_split_point = split_point
            # The first and last ranges should have no lower/upper limit, respectively
            ranges.append([previous_split_point, None])
        else:
            ranges = [(None, None)]
        logger.debug("Key ranges for table %s: %s", queryset.model._meta.db_table, ranges)
        return ranges

    def _get_split_points(self, shard_count):
        samples = self._get_samples()
        # Essentially we use the samples as the split points, this means that in time periods where
        # there are more entities there will be more split points. We just have to reduce the number
        # of samples down until it's (roughly) the same as the number of range boundaries that we
        # need to create.
        ratio = len(samples) // shard_count  # This will err towards more ranges than asked for
        if not ratio:
            # Avoid zero-division fun in modulo when we've got fewer samples than we want shards
            return samples
        split_points = [
            sample for index, sample in enumerate(samples) if not index % ratio
        ]
        return split_points

    def _get_samples(self):
        queryset = QuerySet(model=self.model, query=self.query, using=self.using)
        samples = queryset.values_list(self.sharding_field, flat=True)[:self.sample_size]
        # Remove empty values. We do this in Python to avoid surprising the developer with a query
        # that requires an extra index. They can filter the queryset beforehand if they want.
        samples = {x for x in samples if x}  # Also de-duplicate to avoid weirdness
        # Sort in python, so that we don't cause the need for an additional index
        return sorted(samples)


def firestore_scattered_int_key_ranges(queryset: QuerySet, shard_count: int) -> list:
    """ For Firestore, which (at the time of coding this) can't order by PK descending, this
        provides a crude workaround for getting integer key ranges by simply splitting the maximum
        possible key range into evenly-sized ranges.
    """
    key_ranges = []
    if shard_count > 1:
        # TODO: we could make a significant improvement to this by doing some bisection.
        # Firestore allows __gte/__lte queries, so we could at least narrow down the overall range
        # by doing a (limited) series of `.filter(__gte/lte=X).exists() queries.
        min_value = 1
        max_value = FIRESTORE_MAX_INT
        step_size = max_value // shard_count  # Avoid float-based precision loss
        range_end = 0
        for index, range_start in enumerate(range(min_value, max_value, step_size)):
            if index + 1 == shard_count:  # Last shard
                # This both prevents us overshooting and also deals with the missing remainder
                # for when the max_value doesn't divide by the shard count
                range_end = max_value
                key_ranges.append((range_start, range_end))
                break
            else:
                range_end = range_start + step_size - 1
                key_ranges.append((range_start, range_end))
    else:
        # Don't shard
        key_ranges = [(None, None)]
    return key_ranges


def firestore_name_key_ranges(queryset: QuerySet, shard_count: int) -> list:
    """ For Firestore, which (at the time of coding this) can't order by PK descending, this
        provides a crude workaround for getting key ranges for its auto-generated string-based keys
        by simply splitting the maximum possible key range into evenly-sized ranges.
    """
    return _random_fixed_length_string_ranges(
        FIRESTORE_KEY_NAME_CHARS, FIRESTORE_KEY_NAME_LENGTH, shard_count
    )


def firebase_uid_key_ranges(queryset: QuerySet, shard_count: int) -> list:
    """ Generates shard ranges for Firestore entities whose keys are Firebase Auth UIDs (which are
        28 character ascii strings). As Firestore can't order by PK descending, this generates shard
        ranges by splitting the maximum possible key space into evenly sized ranges.
    """
    return _random_fixed_length_string_ranges(
        FIRESTORE_KEY_NAME_CHARS, FIREBASE_UID_LENGTH, shard_count
    )


def uuid_key_ranges(queryset, shard_count):
    """ Key range generator for UUID strings. """
    # Due to the complication of hyphens, we just work with the characters before the first hyphen
    # to keep things simple. This gives more than enough separation for any sensible shard count,
    # regardless of whether or not the UUIDs are stored in the DB with hyphens.
    uuid_segment_len = str(uuid.uuid4()).index("-") + 1
    return _random_fixed_length_string_ranges("0123456789abcdef", uuid_segment_len, shard_count)


def _random_fixed_length_string_ranges(chars, length, shard_count):
    key_ranges = []
    if shard_count > 1:
        num_possibile_values = len(chars) ** length
        # This avoids inadequate float precision, but means we might undershoot the size of each
        # shard. We add any lost range onto the last shard.
        values_per_shard = num_possibile_values // shard_count
        for index, start_offset in enumerate(range(0, num_possibile_values, values_per_shard)):
            end_offset = start_offset + values_per_shard
            if index == 0:  # First shard
                start_string = None
            else:
                start_string = nth_string(chars, length, start_offset)
            if index + 1 == shard_count:  # Last shard
                end_string = None
            else:
                end_string = nth_string(chars, length, end_offset)
            key_ranges.append((start_string, end_string))
            if end_string is None:
                # Avoid having two end ranges due to the number of possible values not dividing
                # evenly into the number of shards. Eugh.
                break
    else:
        # Don't shard
        key_ranges = [(None, None)]

    return key_ranges


def nth_string(characters: str, length: int, n: int):
    """ Given a string of the characters which can be used, the length of strings to create, and an
        integer, return the string which is the nth alphabetical string of all the strings of that
        length which can be created with those characters.
    """
    max_permutations = len(characters) ** length
    assert n < max_permutations
    # Sort the characters
    sorted_characters = sorted(characters)
    result = ""
    remaining = n
    for _ in range(length):
        char_index = remaining % len(characters)
        result = sorted_characters[char_index] + result
        remaining = remaining // len(characters)
    return result


def get_stable_order(model, order_field):
    if order_field == "pk" or model._meta.get_field(order_field).unique:
        return (order_field, )
    else:
        return (order_field, "pk")


def get_batch_filter(obj, order_field, from_next=True):
    """
        Given a model instance and an order field, this returns the filter
        to continue iteration of an ordered queryset. If from_next is True
        this will return a filter that starts from the next item, if it's
        False the function will return a filter that starts from this item.
    """

    suffix = "gt" if from_next else "gte"
    if order_field == "pk" or obj._meta.pk.name == order_field:
        ret = {f"pk__{suffix}": obj.pk}
    else:
        ret = {
            f"{order_field}__{suffix}": getattr(obj, order_field, None)
        }

    return ret


def iterate_in_chunks(queryset, chunk_size=1000):
    """ Given a queryset (which will become ordered by pk), return an iterable which will fetch its
        objects from the DB in batches of `chunk_size`. This is a temporary workaround for the fact
        that gcloudc doesn't implement Django's chunked fetching of querysets.
    """
    if queryset.query.high_mark or queryset.query.low_mark:
        logger.warning(
            "Cannot iterate queryset for %s in chunks, as it has already been sliced.",
            queryset.model
        )
        # As this function is a generator, we can't just do `return queryset`
        yield from queryset
        return

    offset = 0
    limit = chunk_size

    has_results = True
    while has_results:
        has_results = False
        sliced_queryset = queryset[offset:offset + limit]
        for obj in sliced_queryset.iterator():
            has_results = True
            yield obj

        offset += chunk_size

        if not has_results:
            return
