import itertools
import math

import sleuth
from django.db import models

from djangae.processing import (
    FIRESTORE_KEY_NAME_CHARS,
    FIRESTORE_KEY_NAME_LENGTH,
    FIRESTORE_MAX_INT,
    firestore_name_key_ranges,
    firestore_scattered_int_key_ranges,
    sequential_int_key_ranges,
)
from djangae.test import TestCase


class TestModel(models.Model):
    pass


class ProcessingTestCase(TestCase):
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
            (1, halfway -1),
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
            # Check that the first and last strings are the min and max possible values
            self.assertEqual(ranges[0][0], "0")
            self.assertEqual(
                ranges[-1][1],
                sorted(FIRESTORE_KEY_NAME_CHARS)[-1] * FIRESTORE_KEY_NAME_LENGTH
            )
            # The start/end values should all be in ascending order
            all_values = list(itertools.chain(ranges))
            self.assertEqual(all_values, sorted(all_values))
