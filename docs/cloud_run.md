Cloud Run
=========

Djangae has been primarily developed for running applications on Google App Engine,
but many of the concepts and much of the code are equally as applicable to Google Cloud Run,
and some users have already deployed applications to Cloud Run with a bit of adaptation.

If you're mostly looking for the Google Cloud Datastore backend to use with the Django ORM then
you can simply install the [django-cloud-connectors](https://gitlab.com/potato-oss/google-cloud/django-gcloud-connectors)
sister project into your application and configure the `DATABASES` setting as described in the
[Installation](installation.md) section.


Below is a non-exhaustive list of differences between running Djangae on Cloud Run compared to App Engine.

* The emulators for the Cloud Datastore, Tasks and Storage may need to be run as their own container images, rather than started by `manage.py`. 
* The [incoming `X-Appengine-...` headers(https://cloud.google.com/appengine/docs/standard/python3/reference/request-response-headers) are not sanitised, so cannot be trusted. As such
  - You should not use `djangae.tasks.deferred` out of the box.
  - You should not trust `is_in_cron` or `is_in_task` from `djangae.tasks.environment`.
* With the except of `project_id`, the functions in `djangae.environment` will not behave as expected.
* The `/_ah/warmup` view will not be called for starting up new "instances" of your application, as this concept is [not applicable to Cloud Run](https://github.com/ahmetb/cloud-run-faq#do-i-get-warmup-requests-like-in-app-engine).
* In order to get `request.is_secure()` to behave correctly, you will need to add `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` to your Django settings.

If you use Djangae on Cloud Run, please consider contributing to this documentation with further details.
