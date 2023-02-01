"""
    Tests for djangae.core.paginator to make sure that never does a full
    count on a query.
"""
from django.db import models

from djangae.contrib import sleuth
from djangae.test import TestCase
from djangae.core.paginator import Paginator


class SimplePaginatedModel(models.Model):
    field1 = models.IntegerField(default=0)
    field2 = models.CharField(max_length=10)

    class Meta:
        ordering = ("field1",)


class PaginatorTests(TestCase):
    def setUp(self):
        super(PaginatorTests, self).setUp()

        self.instances = [
            SimplePaginatedModel.objects.create(field1=x, field2=str(x+1))
            for x in range(10)
        ]

    def test_no_previous_on_first_page(self):
        with sleuth.watch('google.cloud.datastore.query.Query.__init__') as query:
            paginator = Paginator(SimplePaginatedModel.objects.all(), 2)

            self.assertFalse(query.called)
            page = paginator.page(1)
            self.assertTrue(query.called)
            self.assertFalse(page.has_previous())

            page = paginator.page(2)
            self.assertTrue(page.has_previous())

    def test_no_next_on_last_page(self):
        paginator = Paginator(SimplePaginatedModel.objects.all(), 2)
        page = paginator.page(5)
        self.assertTrue(page.has_previous())
        self.assertFalse(page.has_next())

        page = paginator.page(4)
        self.assertTrue(page.has_previous())
        self.assertTrue(page.has_next())

    def test_count_raises_error(self):
        paginator = Paginator(SimplePaginatedModel.objects.all(), 2)
        with self.assertRaises(NotImplementedError):
            paginator.count

    def test_num_pages_raises_error(self):
        paginator = Paginator(SimplePaginatedModel.objects.all(), 2)
        with self.assertRaises(NotImplementedError):
            paginator.num_pages

    def test_results_correct(self):
        paginator = Paginator(SimplePaginatedModel.objects.all(), 2)
        page = paginator.page(2)

        self.assertEqual(page[0].field1, 2)
        self.assertEqual(page[1].field1, 3)

        page = paginator.page(3)

        self.assertEqual(page[0].field1, 4)
        self.assertEqual(page[1].field1, 5)
