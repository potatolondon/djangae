## v2.0.0 (in development)

### New features & improvements:

- Added CloudStorageTestCaseMixin to take care of wiping data between tests
- Upgraded the codebase to Python 3
- Added support for Django 2.2, 3.0 and 3.1
- Switched to running the tests using tox (remove testapp etc.)
- Replaced memcache with FileBasedCache (or Memorystore for Redis)
- Replace storage implementation using the new python3 client
- Removed the following:
  - djangae.db (moved to gcloud-connectors)
  - contrib.consistency (new datastore is strongly consistent)
  - contrib.mappers (partially superseded by djangae.tasks)
  - contrib.contenttypes (may come back, originally for eventual consistency reasons)
  - contrib.gauth* (replaced by contrib.googleauth, supporting IAP and Oauth)
  - contrib.processing (partially superseded by djangae.tasks)
  - contrib.uniquetool (unique markers don't exist as new datastore is consistent)
  - djangae.mail (there's no built-in way to send email on Google Cloud)
  - djangae.test_runner / noseplugin (now we have separate emulators for cloud services)
  - djangae.fields (moved to gcloud-connectors)
  - djangae.forms (used for database fields which no longer exist in djangae)
  - lib.memcache (memcache doesn't exist on the Python 3 runtime)
- Control deferred task routing & default to routing tasks to their parent GAE version
- Make `djangae/contrib/security/middleware.py` Python 3.7 compatible
- Update sandbox to allow caller to control emulator ports
- Update `djangae.contrib.backup` and `djangae.contrib.locking` URLs to use the Django 2 `path` function
- Fix backup task credentials for GAE Python 3
- Fix `djangae.contrib.security.commands_utils.extract_views_from_urlpatterns` function
- Fix error classes not inheriting from `Exception`
- Fix an issue with `djangae.storage.CloudStorage` where calling `_open()` or `delete()` wouldn't use the correct bucket
- Add parameter to control datastore emulator `--data-dir`
- Remove `environment.queue_name()` function, use `environment.task_queue_name()` instead
- Update `environment.task_queue_name()` to return `default` if we're in a task and a queue name is not set, otherwise return `None`.
- Replace `environment.application_id()` with `environment.project_id()`, which will work on non-App-Engine environments too.
- Update `djangae/tasks/deferred.py` to handle the case where a queue name is not set
- Add `google-cloud-tasks` as a requirement
- Move `@task_only` to `djangae.decorators`
- Add `@task_or_superuser_only` and `@csrf_exempt_if_task`.
- Allow `defer_iteration_with_finalize` to use different sharding strategy
- Allow custom callable for `djangae.processing.datastore_key_ranges` to generate random keys
- Run datastore emulator with firestore-in-datastore mode enabled
- Update `AppEngineSecurityMiddleware` to support version `6.0`+ of `pyyaml`
- Update `djangae.tasks` to re-use a single Cloud Tasks API client per-thread

### Bug fixes:

- Made pagination cache keys deterministic

## v1.0.1 (bug fix release)

### New features & improvements:
 - Add `max_wait_ms` to `Lock.acquire` which returns early if no lock is available after this long

### Bug fixes:

- Fixes bug where `djangae.contrib.backups` would fail if models shared the same kind.
- Fixes bug where `djangae.contrib.backups` would not backup models who explictly set table name with `db_table`.
- Handle transaction errors when trying to acquire a lock. Improved the retry countdown.

## v1.0.0

### New features & improvements:

- Backup all datastore namespaces.
- Add a `"DEFERRED_ITERATION_SHARD_INDEX"` key to os.environ for callbacks running from `defer_iteration_with_finalize`
- Changed `ensure_instance_included` to `ensure_instance_consistent`

### Bug fixes:

- N/A

## v0.9.12

### New features & improvements:

- Take some steps to make the code Python 3 compatible.
- Additional option to not start mapper pipeline; and provide outputs to finalize function.
- `atomic()` (when used as a context manager) now returns an object representing the current transaction
- Added `djangae.db.transaction.current_transaction()` to return the same thing from inside an `atomic()` decorator
- Added `Transaction.has_been_read(instance)`, `Transaction.has_been_written` and `Transaction.refresh_if_unread(instance)` which allows writing safe transactional code.
- Added `Transaction.has_already_been_read(instance)` and `Transaction.refresh_if_unread(instance)` which allows writing safe transactional code.
- Added App Engine SDK version check on project startup.
- Added support for named class-based views to dumpurls.  Also now supports export to either json or csv
- Added `deferred.defer_iteration_with_finalize`
- Added `Transaction.protect_read` which prevents a specific instance being read inside a transaction.
- Improved `djangae.utils.retry` to catch the Datastore's `InternalError`, and to better select wait times between attempts. Also improved the logging and prevented losing the source of the final exception when retrying fails.
- Updated `djangae.contrib.backup` to use the new export API (the existing API was deprecated in Feb 2018). This adds a dependency of `google-auth` and `google-api-python-client`,
  and also requires some manual permissions to be configured for the app service account. Existing djangae settings will be respected. Read https://cloud.google.com/datastore/docs/schedule-export for details on the new permissions required, and https://cloud.google.com/datastore/docs/export-import-entities
  for an overview including differences between the two APIs.
- Added new option `remove_duplicates` to ListField and RelatedListField which removes duplicated elements and retain order while saving.

### Bug fixes:

- Fixed bug where when running test suite with a target module, if any of the targetted tests had an import error, they were being skipped / silently failing.
- Fixed `ImportError` when running `./manage.py runserver` and the SDK is not already on the Python import path.
- Fix a ValueError when sharding string keys in the migrations mapper library.
- Fixed Djangae's project description on pypi.org.
- Fixed installing dependencies when running tests with pip version 10.
- Worked around a bug where App Engine would return projected values as `str` instead of `unicode`
- Replace binary values in sql value generation with `<binary>` identifier.
- Fix a couple sql unicode bugs.
- Use single quotes for sql string literals, and do not quote integers.
- Fixed a bug in the AsyncMultiQuery that would prevent returning all results in the case when an `OR` query was used with an offset and some entities matched more than one branch of the `OR` query.
- Add an option to ignore pull tasks in testing
- Fix occasions where the default value of a field would not be correctly set on save()
- Simplified the atomic() and non_atomic() decorator/context managers to hopefully eliminate edge-case/threading bugs that have been seen.
- Fix a bug where the context cache would be incorrectly set after leaving a non_atomic block
- Fixed serialization/deserialization of JSONFields
- Fixed migrations failing to map all entities of a kind.
- Mapping queryset should support shard slicing.
- Replaced deprecated resources(`models.get_models`, `models.get_apps` and `Options.module_name`) in `djangae.forms.fields.py`.
- Fixed AttributeError when calling method `UniqueActionAdmin.model_choices()` on `djangae.contrib.uniquetool` app
- Fixed a bug where UUIDField values weren't correctly converted to uuid.UUID objects when read from the Datastore

## v0.9.11

### New features & improvements:

- Backups made with `djangae.contrib.backup` are created in a new, time-stamped directory to make managing backups easier. Only `DJANGAE_BACKUP_ENABLED` is required, all other backup settings are optional and the default is to create backups in the default cloud storage bucket. See the backup docs for details.
- Add support for querying JSONFields in a similar way to the PostgreSQL JSONField
- Allow special indexers to index `None` as well as remove unused index properties from the entity
- Added IDs to system check errors, allowing them to be silenced
- Computed fields now allow the computing function to be passed as a string containing the name of a method, rather than the function object itself.
- `ListField` and `SetField` can now still be pickled when a non-callable default is specified. This was preventing them being used
 in migrations.
- Improve the approx SQL representation of Datastore commands (update, delete etc.)
- Default value for failure_behaviour in `process_task_queues` is now `RAISE_ERROR`. Tasks will no longer fail silently when processed using this method in unit tests.
- Add djangae.compat to handle SDK structural changes
- Added custom `FileField` and `ImageField` which accept an optional `url_field` argument to allow you to specify the name of another field on the model on which the URL to the file or image is cached.
- Add a ComputedNullBooleanField
- Updated the `sleuth` library in djangae.contrib
- Updated the csrf session check to respect Django's `CSRF_USE_SESSIONS` flag
- Improvements to `djangae.utils.retry`:
    - Now allows you to specify which exceptions to catch.
    - Now waits for 375ms by default before retrying to avoid excerbating contention (previous value of 100ms was far too low, and was actually about 0.1ms due to a bug).
    - Now allows overriding the initial retry time with the `_initial_wait` kwarg.
    - Now allows specifying a `_max_wait` time.
    - Now provides an accompanying `@retry_on_error` decorator for applying it to function definitions.
    - Is now documented.
    - changed `_retries` argument to `_attempts` which is better API
- Add `djangae.deferred.defer` to fix issues with `google.appengine.ext.deferred.defer`

### Bug fixes:

 - Fixed ComputedCollationField logic to work with nullable fields
 - Fixed performance issues and bugs in the Djangae core paginator
 - Fix several issues with the test sandbox
 - Initialize the app_identity stub in the test sandbox
 - Replace `print()` statements with `logging.debug()` in all unittests
 - Silence stdout output during testing
 - Logging output silenced during `manage.py test` execution
 - Fix management command `--help` output
 - Create .editorconfig to ensure basic editor settings are consistent between users
 - Fix import error in SDK 1.9.60
 - Add .flake8 file to move towards enforcement code standard
 - Correctly select initial values for SetField form widget
 - Previously `instance.relatedlistfield.all()[0]` would retrieve all items before indexing, now it only grabs the first
 - Fixed `instance.relatedlistfield.values_list(...)` which would die with an error in 0.9.10 and earlier
 - Add missing `djangae/fields/allkeys-5.2.0.zip` file to `MANIFEST.in`
 - It was possible a `TypeError` would throw when calculating the ComputedCollationField value if the source value was unicode
 - Make `value_from_datadict` in `forms.fields.ListWidget` return None when the value provided is None as the existing comment describes. This prevents an exception when `save()` is called on a `ListWidget` whose value is `None`.
 - Fixed test to remove dependency on mock
 - Use '' as default namespace for memcache keys, instead of None.
 - Set a default app_id (`managepy`) so you can use use gcloud compatible app.yaml files (which cannot contain an app_id).  Override with --app_id
 - Restricted access to the `clearsessions` view to tasks and admins only
 - Fixed the `sleep()` time in `djangae.utils.retry` which was sleeping in `ns` rather than `ms`
 - Fix unicode error when creating a SQL representation
 - Fix cross-database relationship support for `RelatedSetField` and `RelatedListField`.
 - Locked down the backup creation view in `djangae.contrib.backups`
 - Fixed the backup creation URL to have a trailing slash (optional, to prevent breaking apps)
 - Fixed an issue with ComputedCollationField where the sort order would be incorrect for some values. (Will need a resave of objects to fix existing data.)

## v0.9.10

### New features & improvements:

 - A new contrib app `djangae.contrib.processing.mapreduce` has been added to provide a Django-friendly API to mapreduce. The existing
   `djangae.contrib.mappers` API has been reimplemented in terms of `djangae.contrib.processing.mapreduce`
 - Add support for the latest App Engine SDK (1.9.51)
 - The default ports for the API server, admin server and blobstore service have changed to 8010, 8011, and 8012 respectively to avoid clashes with modules
 - Switched the default storage backend (in settings_base.py) to cloud storage. If you need to retain compatibility make sure you
 override the `DEFAULT_FILE_STORAGE` setting to point to `'djangae.storage.BlobstoreStorage'`.
 - Added AsyncMultiQuery as a replacement for Google's MultiQuery (which doesn't exist on Cloud Datastore).  This is the first step towards support for Cloud Datastore and therefore Flexible Environment.
 - Added a configurable memory limit to the context cache, limited the number of instances cached from query results and corrected `disable_cache` behaviour.
- Added support for running migrations on the Datastore using Django migrations.
- Added a test to confirm query slicing works correctly.
- Added `ComputedCollationField` to generate correct ordering for unicode strings.
- Changed CloudStorage and BlobstoreStorage storage backends to return HTTPS URLs for images (instead of the previous protocol-relative URLs).
- Implemented an entirely new means of storing the indexes for contains and icontains queries. **If you have existing
  entities which use the current indexing, you MUST set `DJANGAE_USE_LEGACY_CONTAINS_LOGIC = True` in your settings!!**
  This will be removed in the next release of Djangae so you'll need to re-save your entities with this setting set to False before upgrading (see [detailed release notes](docs/release_notes/0_9_10.md)).
- Added support for the 1.9.54 SDK
- Implemented a full application that can be deployed to production GAE for testing real-world scenarios against GCP environment
- Added `djangae.contrib.backup` app

### Bug fixes:

 - When running the local sandbox, if a port clash is detected then the next port will be used (this was broken before)
 - Accessing the Datastore from outside tests will no longer throw an error when using the test sandbox
 - Fix an error which occurred when a migrations module is not importable
 - The in-context cache is now reliably wiped when the testbed is initialized for each test.
 - Fixed an ImportError when the SDK is not on sys.path.
 - Fix issue where serialization of IterableFields resulted in invalid JSON
 - Updated the documenation to say that DJANGAE_CREATE_UNKNOWN_USER defaults to True.
 - Fixed a hard requirement on PIL/Pillow when running the tests. Now, the images stub will not be available if Pillow isn't installed.
 - os.environ is now correctly updated with task headers when using process_task_queues in tests
 - process_task_queues can now be controlled by passing the `failure_behaviour` argument as appropriate
 - process_task_queues will no longer propagate exceptions from tasks, instead use the `failure_behaviour` to control what happens
   if an exception occurs in a task
 - Ensure that the order of values in a RelatedListField are respected when updated via a form.
 - Make mapreduce optional again (#926).
 - Fixed a bug where filter(pk__gt=0) would return no results, rather than all of them
 - We no longer truncate string keys automatically and the max string key length is now the Datastore supported 1500 bytes
 - Fixed AsyncMultiQuery offset and limiting

## v0.9.9 (release date: 27th March 2017)

### New features & improvements:

- Added preliminary support for Django 1.11 (not yet released, don't upgrade yet!)
- The system check for session_csrf now works with the MIDDLEWARE setting when using Django >= 1.10.
- System check for deferred builtin which should always be switched off.
- Implemented weak (memcache) locking to contrib.locking
- The `disable_cache` decorator now wraps the returned function with functools.wraps
- `prefetch_related()` now works on RelatedListField and RelatedSetField
- Added a test for Model.objects.none().filter(pk=xyz) type filters
- Use `user.is_authenticated` instead of `user.is_authenticated()` when using Django >= 1.10.
- Added `max_length` and `min_length` validation support to `ListField`, `SetField`, `RelatedListField` and `RelatedSetField`.
- Moved checks verifying csrf, csp and template loader configuration from djangae-scaffold into Djangae.
- Renamed `contrib.gauth.datastore` and `contrib.gauth.sql` to `contrib.gauth_datastore` and `contrib.gauth_sql` respectively.
    - This change requires you to update your settings to reference the new app names.
    - The old names still work for now but will trigger deprecation warnings.
    - DB table names for Datastore-based models have not changed.  DB table name for the SQL User model has changed, but wasn't entirely usable before anyway.
- Moved everything from `contrib.gauth.common.*` to the parent `contrib.gauth` module.  I.e. removed the `.common` part.
    - This change requires you to update your application to reference/import from the new paths.
    - The old paths still work for now but will trigger deprecation warnings.
- Cleaned up the query fetching code to be more readable. Moved where result fetching happens to be inline with other backends, which makes Django Debug Toolbar query profiling output correct
- Cleaned up app_id handling in --sandbox management calls
- The default GCS bucket name is now cached when first read, saving on RPC calls
- Updated `AppEngineSecurityMiddleware` to work with Django >= 1.10
- Added a test for prefetching via RelatedSetField/RelatedListField. Cleaned up some related code.
- Allow the sandbox argument to be at any position.
- Added some tests for the management command code.
- Added a test to prove that the ordering specified on a model's `_meta` is used for pagination, when no custom order has been specified on the query set.
- Added a `@task_or_admin_only` decorator to `djangae.environment` to allow restricting views to tasks (including crons) or admins of the application.
- Added `GOOGLEAUTH_IAP_JWT_AUDIENCE` setting to allow for IAP JWT validation.

### Bug fixes:

- Fixed a minor bug where entities were still added to memcache (but not fetched from it) with `DJANGAE_CACHE_ENABLED=False`.  This fix now allows disabling the cache to be a successful workaround for https://code.google.com/p/googleappengine/issues/detail?id=7876.
- Fixed a bug where entities could still be fetched from memcache with `DJANGAE_CACHE_ENABLED=False` when saving in a transaction or deleting them.
- Fixed overlap filtering on RelatedListField and RelatedSetField (Thanks Grzes!)
- Fixed various issues with `djangae.contrib.mappers.defer_iteration`, so that it no longers gets stuck deferring tasks or hitting memory limit errors when uses on large querysets.
- Fixed an issue where having a ForeignKey to a ContentType would cause an issue when querying due to the large IDs produced by djangae.contrib.contenttypes's SimulatedContentTypesManager.
- Fix a problem with query parsing which would throw a NotSupportedError on Django 1.8 if you used an empty Q() object in a filter
- Cascade deletions will now correctly batch object collection within the datastore query limits, fixing errors on deletion.
- Fixed missing `_deferred` attribute in Django models for versions >= 1.10
- Fixed an error when submitting an empty JSONFormField
- Fixed a bug where an error would be thrown if you loaded an entity with a JSONField that had non-JSON data, now the data is returned unaltered
- Fixed a bug where only("pk") wouldn't perform a keys_only query
- Dropped the deprecated patterns() from contrib.locking.urls
- Fixed a bug where search indexes weren't saved when they were generated in the local shell
- Fixed a bug where permissions wouldn't be created when using Django's PermissionsMixin on the datastore (for some reason)
- Fixed a bug where a user's username would be set to the string 'None' if username was not populated on an admin form
- Fixed `djangae.contrib.mappers.defer.defer_iteration` to allow inequality filters in querysets
- Fixed a bug in `djangae.contrib.mappers.defer.defer_iteration` where `_shard` would potentially ignore the first element of the queryset
- Fixed an incompatibility between appstats and the cloud storage backend due to RPC calls being made in the __init__ method
- Fixed a bug where it wasn't possible to add validators to djangae.fields.CharField
- Fixed a bug where entries in `RelatedSetField`s and `RelatedListField`s weren't being converted to the same type as the primary key of the model
- Fixed a bug where running tests would incorrectly load the real search stub before the test version
- Fixed a bug where IDs weren't reserved with the datastore allocator immediately and so could end up with a race-condition where an ID could be reused
- Fixed runserver port not being passed to devappserver

### Documentation:

- Improved documentation for `djangae.contrib.mappers.defer_iteration`.
- Changed the installation documentation to reflect the correct way to launch tests


## v0.9.8 (release date: 6th December 2016)

### New features & improvements:

- Cleaned up and refactored internal implementation of `SimulatedContentTypeManager`. Now also allows patching `ContentType` manager in migrations.
- Add ability to specify GAE target instance for remote command with `--app_id` flag
- When App Engine raises an `InvalidSenderError` when trying to send an email, Djangae now logs the 'from' address which is invalid (App Engine doesn't include it in the error).

### Bug fixes:

- Fixed an issue where Django Debug Toolbar would get a `UnicodeDecodeError` if a query contained a non-ascii character.
- Fixed an issue where getting and flushing a specific `TaskQueue` using the test stub (including when using `djangae.test.TestCase.process_task_queues`) would flush all task queues.
- Fixed a bug in our forced contenttypes migration
- Fixed `./manage.py runserver` not working with Django 1.10 and removed a RemovedInDjango110Warning message at startup.
- Restore `--nothreading` functionality to runserver (this went away when we dropped support for the old dev_appserver)
- Fixed a bug where the `dumpurls` command had stopped working due to subtle import changes.
- Utilise `get_serving_url` to get the correct url for serving images from Cloud Storage.
- Fixed a side effect of that ^ introduction of `get_serving_url` which would add an entity group to any transaction in which it was called (due to the Datastore read done by `get_serving_url`).
- Fixed fetching url for non images after introduction of `get_serving_url` call inside `CloudStorage` url method.
- Fixed fetching url for files after introduction of `get_serving_url` call inside `BlobstoreStorage` url method when file is bigger than 32MB.
- Fixed `gauth` middleware to update user email address if it gets changed


## v0.9.7 (release date: 11th August 2016)

### New features & improvements:

- Added support for Django 1.10.
- Changed the querying of `ListField` and `SetField`, which now works similiarly to PostgreSQL ArrayField. `isnull` lookup has been replaced with `isempty`, `exact` with `contains` and `in` with `overlap`. This is a breaking change, so stick to Djangae 0.9.6 or update your code.
- Made a slight efficiency improvement so that `my_queryset.filter(pk__in=other_queryset)` will use `other_queryset.values_list('pk')` rather than fetching the full objects.
- Added clearsessions view.

### Bug fixes:

- Fixed a circular import in djangae.db.utils.
- Fixed sandbox problem with non-final django versions in the testapp.
- Fixed a bug where the console URL stored in a mapreduce job's status entity was incorrect.

### Documentation:

- Added documentation about querying `ListField` and `SetField`.


## v0.9.6 (release date: 1st August 2016)

### New features & improvements:

- ALLOWED_HOSTS is now set to ("*",) by default as App Engine deals with routing and this prevents
  users being confused when their deployed app returns 400 responses.
- Added version string to `__init__`.
- Added an `--install_deps` flag to the `runtests.sh` script to allow triggering of dependency installation without having to delete the SDK folder.
- Added an `--install_sdk` flag to both the `runtests.sh` script and to the `install_deps.py` script in the bundled 'testapp'.
- The `count()` method on `ShardedCounterField` is deprecated because its function was ambiguous or misleading and was often mistakenly used instead of `value()`. It is replaced with a `shard_count()` method.
- It is now possible to have a per-app djangaeidx.yaml file which can be distributed. The indexes in this file
  are combined in memory with the ones from the project root's djangaeidx.yaml. This means that a user of your app
  will not be required to run queries to generate indexes or manually add them to their project file.
- Made a small performance improvement to avoid checking for changes to djangaeindx.yaml files when on production.

### Bug fixes:

- Fixed a regression that prevented precreated users from logging in when `DJANGAE_CREATE_UNKNOWN_USER` is False.
- Fixed a bug where the IntegrityError for a unique constraint violation could mention the wrong field(s).
- Changed the default value of `DJANGAE_CREATE_UNKNOWN_USER` to `True` to match the original behaviour.
- Fixed a bug where simulate contenttypes was required even on a SQL database
- Fixed a bug where filtering on an empty PK would result in an inequality filter being used
- Fixed a bug where making a projection query on time or datetime fields will return truncated values without microseconds
- Fixed a test which could intermittently fail (`test_ordering_on_sparse_field`).
- Fixed a bug where an empty upload_to argument to FileField would result in a broken "./" folder in Cloud Storage.
- Fixed an issue where pre-created users may not have been able to log in if the email address associated with their Google account differed in case to the email address saved in their pre-created User object.
- Made configuration changes to the bundled 'testapp' to allow the `runserver` command to work.
- Fixed a bug in the `install_deps.py` script in the bundled 'testapp' where it would always re-install the App Engine SDK, even if it already existed.

### Documentation:

- Added documentation for:
    - Creating users for gauth.
    - djangaeidx.yaml.
- Improved documentation for:
    - Installation
    - Transactions
    - JSONField
    - RelatedSetField
    - Running management commands locally and remotely
- Fixed incorrect documentation for:
    - The restrictions on projection queries.
- Removed "experimental" flag from the "namespaces" feature of the Datastore DB backend.

## v0.9.5 (release date: 6th June 2016)

### New features & improvements:

- Added the ability to pre-create users in the Django admin who can then log in via Google Accounts.  (Previously you could only pre-create users via the shell.)
- Added new `assert_login_required` and `assert_login_admin` methods to `djangae.test.TestCase`.
- Improved ordering of `sys.path` so that libraries in the application folder take precedence over libraries that are bundled with the SDK (with some hard-to-avoid exceptions).
- Added `djangae.contrib.locking`, for preventing simultaneous executing of functions or blocks of code.
- Moved and renamed several functions from `djangae.utils` to `djangae.environment`.
- Added new task utility functions: `is_in_task()`, `task_name()`, `task_queue_name()`, `task_retry_count()`.
- Extended runserver's file watcher patching to allow ignoring of directories.
- Add tasks utility functions to djangae.environment.
- Alias DatastorePaginator -> Paginator, and DatastorePage -> Page to be more like Django
- Moved `ContentType` patching to `djangae.contrib.contenttypes`. `DJANGAE_SIMULATE_CONTENTTYPES` setting has been removed, add `djangae.contrib.contenttypes` to `INSTALLED_APPS` instead. `djangae.contrib.contenttypes` needs to be after `django.contrib.contenttypes` in the `INSTALLED_APPS` order.
- Allow customization of which user data is synced in gauth `AuthenticationMiddleware`.
- Allow passing `on_change` callback run when ShardedCounter is changed.

### Bug fixes:

- Fixed `atomic` and `non_atomic` transaction decorators/context managers so that they can be called recursively.
- Fix `JSONField` behaviour in forms: it's properly validating JSON string before saving
it and returns json object, not string when accessed through `cleaned_data`.
- Fixing `ListFormField.clean` to return `[]` instead of `None` for empty values.
- Fix computed field `None` values.
- Made retrieving `blob-key` in `BlobstoreFileUploadHandler` easier by using `content_type_extra`. This removes
ugly hacks from before Django 1.7, and fixes issue with regex in `BlobstoreFileUploadHandler` not recognizing
filenames properly.
- Making auth backend catch race condition when creating a new user.
- Fix for `RelatedIterator` that fails when related iterated fields model is set as string.
- Ensure `MapReduceTask `uses the db returned by the application router(s) unless explicitly passed.
- Fixed bug with `__iexact` indexer where values containing underscores would not be correctly indexed.  (Existing objects will need to be re-saved to be correctly indexed.)
- Allow running Djangae tests with non-stable, non-master version of Django.

### Documentation:

- Added a note about `dumpurls` command in documentation
- Updated contributing documentation

## v0.9.4 (release date: 4th April 2016)

This is our first release bringing support for Django 1.9, and dropping support for 1.7.

If you're still using Django 1.7 in your project:
- Upgrade! 1.7 is no longer supported upstream either and has known security issues
- If you can't upgrade, either pin your requirements on 0.9.3 release, or use the 1-7-stable branch, which may receive small fixes if necessary.

### New features & improvements:

 - Added support for Django 1.9
 - The deletion query code has been rewritten entirely to use `DeleteAsync` and now tries to perform deletions in transactional batches of 25. This should result in improved performance but may introduce subtle changes in behaviour, please keep an eye out for issues. For more details take a look at the extensive comment in the `DeleteCommand` class for all the reasons why this is particularly tricky to get right and keep fast.
 - Refactored unique constrains to make them more robust and reliable, fixing edge cases that could cause duplication of unique values.
 - Refactored `InsertCommand` (related to the unique constrains), performance improvements.
 - The Google auth backend has been updated, and a new setting `DJANGAE_CREATE_UNKNOWN_USER` has been added. This replaces the previous settings `DJANGAE_FORCE_USER_PRE_CREATION` and `DJANGAE_ALLOW_USER_PRE_CREATION`.
  - For new projects, `DJANGAE_CREATE_UNKNOWN_USER` defaults to False, meaning you will have to create user objects in the database with matching email addresses to allow people to access your site. For existing projects, the auth backend will recognise the old auth-related settings.
  - If `DJANGAE_CREATE_UNKNOWN_USER=True` then a Django user object will be created automatically when a user accesses your site (if there is no matching user already).
 - Added support for `keep_parents=True` in concrete model inheritance
 - Added support for filters aside from exact on special lookups like `__month` or `__day`. So things like `datefield__month__gt=X` work now
 - Replaced `ensure_instance_included` with `ensure_instance_consistent`
 - Added `ensure_instances_consistent` for the multiple object case
 - Added option to pass `_target` argument to `defer_iteration` in mappers

### Bug fixes:

 - Fixed a bug when saving forms with a RelatedListField or RelatedSetField (#607)
 - JSONField fixes after removing SubfieldBase dependency - to_python added and default value not converted to string anymore

### Documentation:

 - Improvements to storage documentation
 - Replaced links in docs to use https version


## v0.9.3 (release date: 8th March 2016)

### New features & improvements:
- Added support for namespaces
- Refactored cache
- Added Djangae's `CharField` that limits the length by bytes, not characters.
- Improved exception message when encountering multiple inequality filters or uniqueness validation
- Now allowing to override `google_acl` option when uploading to Google Cloud Storage
- Added `BinaryField`
- Added documentation for storage backends
- Added `DJANGAE_IGNORE_REGEXES` settings that allows to only restart dev server for changes on specific filenames. In default, restart dev server only when a `.py`, `.html` or `.yaml` file changes
- Allow `MapReduceTask` tasks to be run on a specific task queue
- Added `ensure_instance_included` to `djangae.db.consistency`
- `djangae.contrib.gauth` now always add users with their emails lowercased
- Provided limited options for `on_delete` on `RelatedSetField` and `RelatedListField`
- Renamed `AppEngineUserAPI` to `AppEngineUserAPIBackend`

### Bug fixes:
- Special indexing now works on fields that are primary keys too
- Fixed a bug with special indexing of datetime fields, that now allows for `__year` or `__month` lookups
- Allow serializing queries containing non-ascii characters
- Don't parse floats as decimals, fixing a bug that causes them to be returned as strings after multiple saves
- `.distinct(x).values_list(x)` no longer cause an error due to the same column being projected twice
- Don't die in `allow_mode_write` if the tempfile module is unavailable
- Fix problems with querying on related fields
- Fixed bug when using `RelatedListField` on a form
- Don't allow ordering by a `TextField`
- Properly limiting number of results when excludes are used
- Allow migrations to work on gauth sql User model
