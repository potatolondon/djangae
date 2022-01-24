
# Easy Efficient Pagination for the Datastore

Pagination on the datastore is *slow*. This is for a couple of reasons:

 - Counting on the datastore is slow; traditional pagination counts the dataset
 - Skipping results on the datastore is slow; if you slice a query, App Engine literally skips the entities up to the lower bound

Djangae provides two pagination tools:

1. `djangae.core.paginator`.  This just provides a `Paginator` class similar to Django's, mostly just for compatability.  It avoids the issue of counting large numbers by not supporting the counting aspects, but it doesn't solve the issue of offsets being slow.
2. `djangae.contrib.pagination`.  This provides a complete pagination solution for the Datastore.  This article focusses on this.

## So, what does djangae.contrib.pagination do?

This app provides two things that work together to efficiently paginate datasets on the datastore:

 - `@paginated_model` - A class decorator that dynamically generates (a) precalculated field(s) on a model,
    which can be used for ordering and `__gt` filtering, rather than doing inefficient slicing.
 - `Paginator` - A Paginator subclass which uses the precalculated field(s) along with memcache to
efficiently paginate and doesn't count all the results.

### Can you explain that a bit more?

Supposing you have a queryset like this:

    queryset = MyModel.objects.order_by('first_name', 'last_name')

and you then want to paginate with 100 objects per page.  Your query for page 2 will be
`queryset[200:299]`, which will cause the Datastore iterate over the first 200 entities before then
returning entities 200-299, which is inefficient.  However, if we create a pre-calculated field,
made up of the fields we want to order by, plus a unique-ifier, (e.g.
`"%s|%s|%s" % (first_name, last_name, pk)`), then we can order by that single field.  For
pagination, when we fetch page 1, we can store the value of this field from the last object of page 1.
The query for page 2 can then be

    MyModel.objects.order_by('pre_calculated_field').filter(pre_calculated_field__gt=page_1_last_value)

which avoids any slicing at all.  The whole query and offset is based on Datastore indexes, and is efficient.

The `@paginated_model` decorator allows you to specify which field(s) on your model you want to order
by (you can specify multiple orderings for a model) and generates the pre-calculated fields for you.
The `DatastorePaginator` then seemlessly uses these pre-calculated fields and does the offset/limiting for you.

The `lookahead` argument to the paginator tells it how many pages ahead it should look.  E.g. if
you set lookahead to `10` then it will query ahead to find the offset value to allow it to jump 10 pages.


## Wait, doesn't the datastore have cursors?

Yes! However from the docs:

> Because the != and IN operators are implemented with multiple queries, queries that use them do not support cursors.

That's a hell of an annoying caveat. That's not to say our approach doesn't suffer it's own caveats (below), but it does support IN and != queries.

## Caveats

Because our pre-calculated fields are indexed, the combined length of the values (plus the unique ID and joining characters) you are
ordering on must not exceed 1500 characters. This will throw an error, and if that happens, you'll either need to use a slower paginator (e.g. djangae.core.paginator)
or rethink your design.

## Why didn't you update potatopage?

[Potatopage](https://github.com/potatolondon/potatopage) supports different backends for pagination. I didn't extend that for the following reasons:

 - Efficient pagination is something that pretty much any Djangae-based app needs and should come built-in, moving potatopage into Djangae wouldn't make
 sense as it has backends for Djangoappengine and NDB and they don't belong in Djangae. Potatopage is better as a standalone library anyway.
 - This paginator uses class decorators, the ones in potatopage do not, and it would be weird to have a different API depending on the backend.
 - The only way to really make a suitable backend for potatopage would be to expose the App Engine cursors in Djangae somehow, but this wouldn't work for
 many queries due to the features and optimizations that the smart datastore connector performs (e.g. datastore.Get lookups, support for OR queries etc.)
 and it would be ugly and hacky.

## Can you give me an example?

Sure!

```
from djangae.contrib.pagination import paginated_model

# The paginated_model decorator takes a list of orderings, where each ordering is a field name or a list of field names

@paginated_model(orderings=[
    "first_name",
    "last_name",
    ("first_name", "last_name"),
    ("first_name", "-last_name")
])
class TestUser(models.Model):
    first_name = models.CharField(max_length=200)
    last_name = models.CharField(max_length=200)

    def __unicode__(self):
        return u" ".join([self.first_name, self.last_name])
```

By decorating the model this way, special computed properties are added for ordering by first and last name. Then you can just do this:


```
from djangae.contrib.pagination import Paginator

def listing(request):
    contact_list = TestUser.objects.order_by("first_name")
    paginator = Paginator(contact_list, 25, readahead=10) # Show 25 testusers per page, readahead 10 pages

    page = request.GET.get('page')
    try:
        # Under the hood this will instead order and filter by the magically generated field for
        # first_name, allowing you to efficiently jump to a specific page
        contacts = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        contacts = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        contacts = paginator.page(paginator.num_pages)

    return render_to_response('list.html', {"contacts": contacts})
```

## Configuation

The Paginator caches the values for offsetting the queries.  You can configure the cache expiry time
by defining `settings.DJANGAE_PAGINATION_CACHE_TIME`.
