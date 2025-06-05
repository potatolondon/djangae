import datetime

from django.core import paginator as django_paginator
from django.db import models

from djangae.test import TestCase
from djangae.contrib import sleuth
from djangae.contrib.pagination import (
    paginated_model,
    Paginator,
    PaginationOrderingRequired
)

from .paginator import (
    queryset_identifier,
    _get_marker,
)


@paginated_model(orderings=[
    "first_name",  # single field declared as a string
    ("last_name",),  # single field declared as a tuple
    ("first_name", "last_name"),
    ("first_name", "-last_name"),
    ("created",),
    ("-created",),
    "pk",  # it's possible to order by the model pk
])
class TestUser(models.Model):
    first_name = models.CharField(max_length=200)
    last_name = models.CharField(max_length=200)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return " ".join([self.first_name, self.last_name])

    class Meta:
        ordering = ("first_name", "last_name")


@paginated_model(orderings=[
    "name",
    "pk",  # it's possible to order by the model pk
])
class SimpleModelWithoutOrdering(models.Model):
    name = models.CharField(max_length=200)


@paginated_model(orderings=[
    ("date",),
    "pk",  # it's possible to order by the model pk
])
class SimpleModelWithDate(models.Model):
    date = models.DateTimeField()


class SimpleModelWithOrdering(SimpleModelWithoutOrdering):
    class Meta:
        ordering = ["name"]


class PaginatedModelTests(TestCase):
    def test_fields_added_correctly(self):
        self.assertIsNotNone(TestUser._meta.get_field("pagination_first_name"))
        self.assertIsNotNone(TestUser._meta.get_field("pagination_last_name"))
        self.assertIsNotNone(TestUser._meta.get_field("pagination_first_name_last_name"))
        self.assertIsNotNone(TestUser._meta.get_field("pagination_first_name_neg_last_name"))
        self.assertIsNotNone(TestUser._meta.get_field("pagination_created"))

    def test_precalculate_field_values(self):
        user = TestUser.objects.create(pk=1, first_name="Luke", last_name="Benstead")

        self.assertEqual(u"Luke\x001", user.pagination_first_name)
        self.assertEqual(u"Benstead\x001", user.pagination_last_name)
        self.assertEqual(u"Luke\x00Benstead\x001", user.pagination_first_name_last_name)
        self.assertEqual("%s\x001" % user.created.isoformat(), user.pagination_created)

        reversed_last_name = "".join([chr(0xffff - ord(x)) for x in "Benstead"])

        self.assertEqual(u"Luke\x00{}\x001".format(reversed_last_name), user.pagination_first_name_neg_last_name)


class DatastorePaginatorTests(TestCase):
    def setUp(self):
        super(DatastorePaginatorTests, self).setUp()

        self.u1 = TestUser.objects.create(id=1, first_name="A", last_name="A")
        self.u2 = TestUser.objects.create(id=2, first_name="A", last_name="B")
        self.u3 = TestUser.objects.create(id=3, first_name="B", last_name="A")
        self.u4 = TestUser.objects.create(id=4, first_name="B", last_name="B")

    def test_default_ordering(self):
        """ Tests that pagination works using just the model's default ordering. """
        paginator = Paginator(TestUser.objects.all(), 1, readahead=2)
        paginator.page(1)
        self.assertEqual([self.u1, self.u2, self.u3, self.u4], list(paginator.object_list))

    def test_ordering(self):
        paginator = Paginator(TestUser.objects.all().order_by("created"), 1, readahead=2)
        paginator.page(1)
        self.assertEqual([self.u1, self.u2, self.u3, self.u4], list(paginator.object_list))

        paginator = Paginator(TestUser.objects.all().order_by("-created"), 1, readahead=2)
        paginator.page(1)
        self.assertEqual([self.u4, self.u3, self.u2, self.u1], list(paginator.object_list))

    def test_count_up_to(self):
        paginator = Paginator(TestUser.objects.all().order_by("first_name"), 1, readahead=2)
        paginator.page(1)
        self.assertEqual(3, paginator.count)

        paginator = Paginator(TestUser.objects.all().order_by("first_name"), 1, readahead=10)
        paginator.page(1)
        self.assertEqual(4, paginator.count)

    def test_count_reads_ahead(self):
        paginator = Paginator(TestUser.objects.all().order_by("first_name"), 1, readahead=2)

        paginator.page(1)
        self.assertEqual(3, paginator.count)

        paginator.page(3)
        self.assertEqual(4, paginator.count)

    def test_page_jump_updates_count_correctly(self):
        paginator = Paginator(TestUser.objects.all().order_by("first_name"), 1, readahead=1)
        paginator.page(1)
        self.assertEqual(2, paginator.count)
        paginator.page(3)
        self.assertEqual(4, paginator.count)

    def test_that_marker_is_read(self):
        paginator = Paginator(TestUser.objects.all().order_by("first_name"), 1, readahead=1)
        paginator.page(2)

        with sleuth.watch("djangae.contrib.pagination.paginator._get_marker") as get_marker:
            paginator.page(4)

            self.assertTrue(get_marker.called)
            self.assertIsNotNone(get_marker.call_returns[0][0])
            self.assertEqual(1, get_marker.call_returns[0][1])

    def test_that_readahead_stores_markers(self):
        paginator = Paginator(TestUser.objects.all().order_by("first_name"), 1, readahead=4)

        expected_markers = [None] + list(
            TestUser.objects.all().order_by("first_name").
            values_list(paginator.field_required, flat=True)
        )[:3]

        paginator.page(1)

        query_id = queryset_identifier(paginator.object_list)

        actual_markers = []
        for i in range(1, 5):
            actual_markers.append(_get_marker(query_id, i)[0])

        self.assertEqual(expected_markers, actual_markers)

        # Now change the per page number
        paginator = Paginator(TestUser.objects.all().order_by("first_name"), 2, readahead=4)

        all_markers = list(TestUser.objects.all().order_by("first_name").values_list(
            paginator.field_required, flat=True)
        )
        expected_markers = [None, all_markers[1]]

        paginator.page(1)

        query_id = queryset_identifier(paginator.object_list)

        actual_markers = []
        for i in range(1, 3):
            actual_markers.append(_get_marker(query_id, i)[0])

        self.assertEqual(expected_markers, actual_markers)

    def test_ordering_required_exception_is_thrown_when_no_order_specified(self):
        # The exception should not be thrown when an order is specified
        query_set = SimpleModelWithoutOrdering.objects.order_by("name")
        Paginator(query_set, 25, readahead=10)

        # The exception should not be thrown when the model has a default order
        query_set = SimpleModelWithOrdering.objects.all()
        Paginator(query_set, 25, readahead=10)

        # The exception should be thrown when no order is specified on the model or in the query set
        query_set = SimpleModelWithoutOrdering.objects.all()
        with self.assertRaises(PaginationOrderingRequired):
            Paginator(query_set, 25, readahead=10)

    def test_pages_correct(self):
        paginator = Paginator(TestUser.objects.all().order_by("first_name"), 1)  # 1 item per page

        self.assertEqual("A", paginator.page(1).object_list[0].first_name)
        self.assertEqual("A", paginator.page(2).object_list[0].first_name)
        self.assertEqual("B", paginator.page(3).object_list[0].first_name)
        self.assertEqual("B", paginator.page(4).object_list[0].first_name)

        paginator = Paginator(TestUser.objects.all().order_by("first_name", "last_name"), 1)  # 1 item per page
        self.assertEqual(self.u1, paginator.page(1).object_list[0])
        self.assertEqual(self.u2, paginator.page(2).object_list[0])
        self.assertEqual(self.u3, paginator.page(3).object_list[0])
        self.assertEqual(self.u4, paginator.page(4).object_list[0])

        paginator = Paginator(TestUser.objects.all().order_by("first_name", "-last_name"), 1)  # 1 item per page
        self.assertEqual(self.u2, paginator.page(1).object_list[0])
        self.assertEqual(self.u1, paginator.page(2).object_list[0])
        self.assertEqual(self.u4, paginator.page(3).object_list[0])
        self.assertEqual(self.u3, paginator.page(4).object_list[0])

        paginator = Paginator(TestUser.objects.all().order_by("-first_name"), 1)  # 1 item per page
        self.assertEqual(self.u4, paginator.page(1).object_list[0])
        self.assertEqual(self.u3, paginator.page(2).object_list[0])
        self.assertEqual(self.u2, paginator.page(3).object_list[0])
        self.assertEqual(self.u1, paginator.page(4).object_list[0])

        with self.assertRaises(PaginationOrderingRequired):
            paginator = Paginator(TestUser.objects.all().order_by("-first_name", "last_name"), 1)  # 1 item per page
            list(paginator.page(1).object_list)

        # Test paging when last page has less than per_page objects
        paginator = Paginator(TestUser.objects.all().order_by("first_name"), 3)  # 3 items per page
        self.assertEqual(
            sorted([self.u1.pk, self.u2.pk, self.u3.pk]),
            sorted([x.pk for x in paginator.page(1).object_list])
        )
        self.assertEqual(
            sorted([self.u4.pk]),
            sorted([x.pk for x in paginator.page(2).object_list])
        )

    def test_empty_page(self):
        paginator = Paginator(TestUser.objects.all().order_by("-first_name"), 1, allow_empty_first_page=False)
        with self.assertRaises(django_paginator.EmptyPage):
            self.assertEqual(paginator.page(5).object_list, [])

        paginator = Paginator(TestUser.objects.all().order_by("-first_name"), 1)
        self.assertEqual(paginator.page(5).object_list, [])

    def test_min_max_date_page(self):

        d1 = SimpleModelWithDate.objects.create(id=2, date=datetime.datetime.min)
        d2 = SimpleModelWithDate.objects.create(id=3, date=datetime.datetime.min)
        d3 = SimpleModelWithDate.objects.create(id=1, date=datetime.datetime.max)

        paginator = Paginator(SimpleModelWithDate.objects.all().order_by("date"), 1)
        self.assertEqual(d1, paginator.page(1).object_list[0])
        self.assertEqual(d2, paginator.page(2).object_list[0])
        self.assertEqual(d3, paginator.page(3).object_list[0])
