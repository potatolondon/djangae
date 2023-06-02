import datetime

from django.db import models

from djangae.contrib.pagination import paginated_model
from djangae.test import TestCase


@paginated_model(orderings=[('field',)])
class DateTimePaginatedModel(models.Model):
    field = models.DateTimeField()


class PaginationTests(TestCase):

    def test_datetime(self):

        est = datetime.timezone(-datetime.timedelta(hours=5))
        DateTimePaginatedModel.objects.create(
            field=datetime.datetime(2023, 2, 2, 18, tzinfo=est))
        m2 = DateTimePaginatedModel.objects.create(
            field=datetime.datetime(2023, 2, 2, 22, tzinfo=est))
        DateTimePaginatedModel.objects.create(
            field=datetime.datetime(2023, 2, 3, 22, tzinfo=est))
        DateTimePaginatedModel.objects.create(
            field=datetime.datetime(2023, 2, 2, 18, tzinfo=datetime.timezone.utc))
        DateTimePaginatedModel.objects.create(
            field=datetime.datetime(2023, 2, 2, 22, tzinfo=datetime.timezone.utc))
        m6 = DateTimePaginatedModel.objects.create(
            field=datetime.datetime(2023, 2, 3, 22, tzinfo=datetime.timezone.utc))

        results = list(DateTimePaginatedModel.objects.filter(
            pagination_field__gt=datetime.datetime(2023, 2, 3, 0,
                                                   tzinfo=datetime.timezone.utc).isoformat(),
            pagination_field__lt=datetime.datetime(2023, 2, 4, 0,
                                                   tzinfo=datetime.timezone.utc).isoformat()
        ).order_by('pagination_field'))

        self.assertEqual([r.id for r in results], [m2.id, m6.id])
