from django.db import models
from django.utils import timezone
from djangae.processing import sequential_int_key_ranges
from djangae.tasks.deferred import (
    defer_iteration_with_finalize,
    get_deferred_shard_index,
)
from djangae.test import (
    TaskFailedBehaviour,
    TestCase,
)

import time


_SHARD_COUNT = 5


class DeferIterationTestModel(models.Model):
    touched = models.BooleanField(default=False)
    finalized = models.BooleanField(default=False)
    ignored = models.BooleanField(default=False)


class DeferStringKeyModel(models.Model):
    name = models.CharField(primary_key=True, max_length=32)
    other = models.CharField(max_length=32)
    time_hit = models.DateTimeField(null=True)

    class Meta:
        ordering = (
            "-other",
        )


class DeferIntegerKeyModel(models.Model):
    id = models.IntegerField(primary_key=True)
    touched = models.BooleanField(default=False)
    finalized = models.BooleanField(default=False)


def callback(instance, touch=True):
    shard_index = get_deferred_shard_index()

    assert(shard_index >= 0)
    assert(shard_index < 5)

    if touch:
        instance.touched = True
    instance.save()


sporadic_error_counter = 0


def sporadic_error(instance):
    global sporadic_error_counter

    if instance.pk == 1:
        sporadic_error_counter += 1
        if sporadic_error_counter in (0, 1, 2):
            raise ValueError("Boom!")

    instance.touched = True
    instance.save()


def finalize(*args, **kwargs):
    DeferIterationTestModel.objects.all().update(finalized=True)


def finalize_int(*args, **kwargs):
    DeferIntegerKeyModel.objects.all().update(finalized=True)


def update_timestamp(instance):
    instance.time_hit = timezone.now()
    instance.save()
    time.sleep(0.1)


def noop(*args, **kwargs):
    pass


class DeferIterationTestCase(TestCase):
    def test_passing_args_and_kwargs(self):
        [DeferIterationTestModel.objects.create() for i in range(25)]

        defer_iteration_with_finalize(
            DeferIterationTestModel.objects.all(),
            callback,
            finalize,
            touch=False,  # kwarg to not touch the objects at all
            _shards=_SHARD_COUNT
        )

        self.process_task_queues()

        self.assertEqual(0, DeferIterationTestModel.objects.filter(touched=True).count())

    def test_instances_hit(self):
        [DeferIterationTestModel.objects.create() for i in range(25)]

        defer_iteration_with_finalize(
            DeferIterationTestModel.objects.all(),
            callback,
            finalize,
            _shards=_SHARD_COUNT
        )

        self.process_task_queues()

        self.assertEqual(25, DeferIterationTestModel.objects.filter(touched=True).count())
        self.assertEqual(25, DeferIterationTestModel.objects.filter(finalized=True).count())

    def test_excluded_missed(self):
        [DeferIterationTestModel.objects.create(ignored=(i < 5)) for i in range(25)]

        defer_iteration_with_finalize(
            DeferIterationTestModel.objects.filter(ignored=False),
            callback,
            finalize,
            _shards=_SHARD_COUNT
        )

        self.process_task_queues()

        self.assertEqual(5, DeferIterationTestModel.objects.filter(ignored=True).count())
        self.assertEqual(20, DeferIterationTestModel.objects.filter(touched=True).count())
        self.assertEqual(25, DeferIterationTestModel.objects.filter(finalized=True).count())

    def test_shard_continue_on_error(self):
        [DeferIterationTestModel.objects.create(pk=i + 1) for i in range(25)]

        global sporadic_error_counter
        sporadic_error_counter = 0

        defer_iteration_with_finalize(
            DeferIterationTestModel.objects.all(),
            sporadic_error,
            finalize,
            _shards=_SHARD_COUNT
        )

        self.process_task_queues(failure_behaviour=TaskFailedBehaviour.RETRY_TASK)

        self.assertEqual(25, DeferIterationTestModel.objects.filter(touched=True).count())
        self.assertEqual(25, DeferIterationTestModel.objects.filter(finalized=True).count())

    def test_shard_iterated_in_order(self):
        DeferStringKeyModel.objects.create(name="D", other="A")
        DeferStringKeyModel.objects.create(name="B", other="B")
        DeferStringKeyModel.objects.create(name="A", other="C")
        DeferStringKeyModel.objects.create(name="C", other="D")
        DeferStringKeyModel.objects.create(name="E", other="E")

        defer_iteration_with_finalize(
            DeferStringKeyModel.objects.all(),
            update_timestamp,
            noop,
            _shards=2
        )

        self.process_task_queues()

        instances = DeferStringKeyModel.objects.order_by("time_hit")

        last_id = "\0"

        for instance in instances:
            self.assertTrue(instance.pk > last_id)
            last_id = instance.pk

        # Now test that we can order by a different field other than pk
        defer_iteration_with_finalize(
            DeferStringKeyModel.objects.all(),
            update_timestamp,
            noop,
            order_field="other",
            _shards=2
        )

        self.process_task_queues()

        instances = DeferStringKeyModel.objects.order_by("time_hit")

        last_other = "\0"
        for instance in instances:
            self.assertTrue(instance.other > last_other)
            last_other = instance.other

    def test_autoint_hits(self):
        [DeferIntegerKeyModel.objects.create(id=i+1) for i in range(25)]
        defer_iteration_with_finalize(
            DeferIntegerKeyModel.objects.all(),
            callback,
            finalize_int,
            key_ranges_getter=sequential_int_key_ranges,
            _shards=_SHARD_COUNT
        )

        self.process_task_queues()

        self.assertEqual(25, DeferIntegerKeyModel.objects.filter(touched=True).count())
        self.assertEqual(25, DeferIntegerKeyModel.objects.filter(finalized=True).count())
