import itertools
import math
import random
import sys
import uuid

from djangae.contrib import sleuth
from django.db import models

from djangae.processing import (
    FIRESTORE_KEY_NAME_CHARS,
    FIRESTORE_KEY_NAME_LENGTH,
    FIRESTORE_MAX_INT,
    FIRESTORE_UID_LENGTH,
    SampledKeyRangeGenerator,
    firestore_name_key_ranges,
    firestore_scattered_int_key_ranges,
    iterate_in_chunks,
    sequential_int_key_ranges,
    uuid_key_ranges,
)
from djangae.test import TestCase


class TestModel(models.Model):
    # A field that will have some randomly scattered values. Avoid UUIDField, as its
    # not-actually-a-string nature makes it a bit awkward.
    field1 = models.CharField(max_length=100, default=lambda: str(uuid.uuid4()))


class KeyGeneratorsTestCase(TestCase):

    def test_sampled_key_range_generator(self):
        shard_count = 5
        for _ in range(shard_count * 4):
            TestModel.objects.create()
        sample_queryset = TestModel.objects.order_by("id")
        ranges_generator = SampledKeyRangeGenerator(sample_queryset, "field1")
        processing_queryset = TestModel.objects.all()
        ranges = ranges_generator(processing_queryset, shard_count)
        # The number of ranges might be slightly off due to the sampling
        self.assertGreater(len(ranges), 3)
        self.assertLess(len(ranges), 7)
        self.assert_string_ranges_contiguous(ranges)
        random_uuid = str(uuid.uuid4())
        self.assert_contained_once(random_uuid, ranges)

    def test_sequential_int_key_ranges(self):
        with sleuth.fake("django.db.models.query.QuerySet.first", return_value=0):
            with sleuth.fake("django.db.models.query.QuerySet.last", return_value=1000):
                ranges = sequential_int_key_ranges(TestModel.objects.all(), 1)
                self.assertEqual(ranges, [(0, 1001)])

                ranges = sequential_int_key_ranges(TestModel.objects.all(), 100)
                self.assertEqual(ranges[0], (0, 10))
                self.assertEqual(ranges[1], (10, 20))
                self.assertEqual(ranges[-1], (990, 1001))
                self.assertEqual(len(ranges), 100)

                ranges = sequential_int_key_ranges(TestModel.objects.all(), 2000)
                self.assertEqual(ranges[0], (0, 1))
                self.assertEqual(ranges[1], (1, 2))
                self.assertEqual(ranges[-1], (999, 1001))
                self.assertEqual(len(ranges), 1000)

    def test_sequential_int_key_ranges_non_zero_first(self):
        with sleuth.fake("django.db.models.query.QuerySet.first", return_value=900):
            with sleuth.fake("django.db.models.query.QuerySet.last", return_value=1000):
                ranges = sequential_int_key_ranges(TestModel.objects.all(), 1)
                self.assertEqual(ranges, [(900, 1001)])

                ranges = sequential_int_key_ranges(TestModel.objects.all(), 10)
                self.assertEqual(ranges[0], (900, 910))
                self.assertEqual(ranges[1], (910, 920))
                self.assertEqual(ranges[-1], (990, 1001))
                self.assertEqual(len(ranges), 10)

                ranges = sequential_int_key_ranges(TestModel.objects.all(), 2000)
                self.assertEqual(ranges[0], (900, 901))
                self.assertEqual(ranges[1], (901, 902))
                self.assertEqual(ranges[-1], (999, 1001))
                self.assertEqual(len(ranges), 100)

    def test_sequential_int_key_ranges_negative_first(self):
        with sleuth.fake("django.db.models.query.QuerySet.first", return_value=-1000):
            with sleuth.fake("django.db.models.query.QuerySet.last", return_value=1000):
                ranges = sequential_int_key_ranges(TestModel.objects.all(), 1)
                self.assertEqual(ranges, [(-1000, 1001)])

                ranges = sequential_int_key_ranges(TestModel.objects.all(), 200)
                self.assertEqual(ranges[0], (-1000, -990))
                self.assertEqual(ranges[1], (-990, -980))
                self.assertEqual(ranges[-1], (990, 1001))
                self.assertEqual(len(ranges), 200)

                ranges = sequential_int_key_ranges(TestModel.objects.all(), 4000)
                self.assertEqual(ranges[0], (-1000, -999))
                self.assertEqual(ranges[1], (-999, -998))
                self.assertEqual(ranges[-1], (999, 1001))
                self.assertEqual(len(ranges), 2000)

    def test_firestore_scattered_int_key_ranges(self):
        queryset = TestModel.objects.all()
        # For a shard count of 1, we expect no sharding
        ranges = firestore_scattered_int_key_ranges(queryset, 1)
        self.assertEqual(ranges, [(None, None)])
        # For a two shards we expect them to split at the halfway point
        ranges = firestore_scattered_int_key_ranges(queryset, 2)
        halfway = math.ceil(FIRESTORE_MAX_INT / 2)
        expected = [
            (1, halfway - 1),
            (halfway, FIRESTORE_MAX_INT)
        ]
        self.assertEqual(ranges, expected)
        # For more shards, we'll do some less exact checks
        for shard_count in (3, 7, 14):
            ranges = firestore_scattered_int_key_ranges(queryset, shard_count)
            self.assertEqual(len(ranges), shard_count)
            # The start/end values should all be in ascending order
            all_values = list(itertools.chain(ranges))
            self.assertEqual(all_values, sorted(all_values))
            # And the start of each range should be 1 more than the end of the previous range
            previous_range_end = 0
            for range_start, range_end in ranges:
                self.assertEqual(range_start, previous_range_end + 1)
                previous_range_end = range_end

    def test_firestore_name_key_ranges(self):
        queryset = TestModel.objects.all()
        # For a shard count of 1, we expect no sharding
        ranges = firestore_name_key_ranges(queryset, 1)
        self.assertEqual(ranges, [(None, None)])
        # Test for various shard counts
        for shard_count in (3, 7, 14):
            ranges = firestore_name_key_ranges(queryset, shard_count)
            self.assertEqual(len(ranges), shard_count)
            self.assert_string_ranges_contiguous(ranges)
            random_firestore_id = "".join(
                random.choice(FIRESTORE_KEY_NAME_CHARS)
                for _ in range(FIRESTORE_KEY_NAME_LENGTH)
            )
            self.assert_contained_once(random_firestore_id, ranges)

    def test_firestore_uid_ranges(self):
        queryset = TestModel.objects.all()
        # For a shard count of 1, we expect no sharding
        ranges = firestore_name_key_ranges(queryset, 1)
        self.assertEqual(ranges, [(None, None)])
        # Test for various shard counts
        for shard_count in (3, 7, 14):
            ranges = firestore_name_key_ranges(queryset, shard_count)
            self.assertEqual(len(ranges), shard_count)
            self.assert_string_ranges_contiguous(ranges)
            random_firestore_uid = "".join(
                random.choice(FIRESTORE_KEY_NAME_CHARS)
                for _ in range(FIRESTORE_UID_LENGTH)
            )
            self.assert_contained_once(random_firestore_uid, ranges)

    def test_uuid_key_ranges(self):
        queryset = TestModel.objects.all()
        # For a shard count of 1, we expect no sharding
        ranges = uuid_key_ranges(queryset, 1)
        self.assertEqual(ranges, [(None, None)])
        # Test for various shard counts
        for shard_count in (3, 7, 14):
            ranges = uuid_key_ranges(queryset, shard_count)
            self.assertEqual(len(ranges), shard_count)
            self.assert_string_ranges_contiguous(ranges)
            random_uuid = str(uuid.uuid4())
            self.assert_contained_once(random_uuid, ranges)
            # Test without hyphens, which is how Django stores them
            random_uuid = str(uuid.uuid4()).replace("-", "")
            self.assert_contained_once(random_uuid, ranges)

    def assert_string_ranges_contiguous(self, ranges, msg=None):
        """ Check that the given list of pairs doesn't contain any overlapping values and doesn't
            contain any gaps.
        """
        msg = msg or self._print_ranges(ranges)
        ranges = sorted(ranges, key=lambda range_: range_[0] or "")
        self.assertIsNone(ranges[0][0], f"Expected lower bound of first range to be None. {msg}")
        self.assertIsNone(ranges[-1][1], f"Expected upper bound of last range to be None. {msg}")
        previous_upper_bound = ranges[0][1]
        for range_ in ranges[1:]:
            self.assertLess(range_[0] or "", range_[1] or chr(sys.maxunicode), msg)
            self.assertEqual(range_[0], previous_upper_bound, msg)
            previous_upper_bound = range_[1]

    def assert_contained_once(self, value, ranges):
        contains = [range_ for range_ in ranges if self._contains(range_, value)]
        self.assertEqual(
            len(contains),
            1,
            f"Value {value} is not contained by 1 range. {self._print_ranges(ranges)}"
        )

    def _print_ranges(self, ranges):
        return "\nRanges:\n    " + (
            "\n    ".join([str(x) for x in ranges])
        )

    def _contains(self, range_, value):
        if range_[0] is None:
            return value <= range_[1]
        if range_[1] is None:
            return value > range_[0]
        return range_[0] < value <= range_[1]


class IterateInChunksTestCase(TestCase):

    def test_iterate_in_chunks(self):
        """ Test the `iterate_in_chunks` function. """
        for _ in range(5):
            TestModel.objects.create()
        queryset = TestModel.objects.all()
        # Test iterating the whole thing with the default chunk size
        results = [x for x in iterate_in_chunks(queryset)]
        self.assertEqual(len(results), 5)
        # Test iterating with a smaller chunk size
        results = [x for x in iterate_in_chunks(queryset, chunk_size=3)]
        self.assertEqual(len(results), 5)
        # Test when there is a limit on the queryset
        queryset = queryset[:4]
        results = [x for x in iterate_in_chunks(queryset)]
        self.assertEqual(len(results), 4)
        results = [x for x in iterate_in_chunks(queryset, chunk_size=3)]
        self.assertEqual(len(results), 4)
