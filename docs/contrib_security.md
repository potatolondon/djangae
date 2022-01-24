# Security

Djangae-scaffold provides a good skeleton project setup with various security libraries included
and settings configured as a starting point.

Djangae also provides the following features to aid security:

## Security Middleware

`djangae.contrib.security.middleware.AppEngineSecurityMiddleware` is a Django middleware which
patches certain parts of App Engine and its libraries, specifically:

* The Python `yaml` library is patched so that the default loader is `yaml.loader.SafeLoader` in order to prevent arbitrary Python code execution.
* The Python `json` library is patched so that the default encoder class escapes the HTML entities `<`, `>` and `&`.

This middleware applies the patches and then raises `django.core.exceptions.MiddlewareNotUsed` so that it does not re-apply the patches on subsequent requests.  Note that in tests which don't load any middleware the patches will not be applied.


## `dumpurls` Management Command

Use the `dumpurls` management command to generate a report listing all the configured URL patterns in your project.

For each pattern, the report shows the regular expression for the full path, the Python dotted module name for the view that handles requests, and the names of decorators that may have been applied to the view.

Supports the following optional parameters:

* `--show_allowed_methods` HTTP methods supported by this view (CBVs only)
* `--show_class_parents` CBVs only.  Shows which classes this view inherits from
* `--output_file_type` Export dumpurl data to a json or csv file.  Choices: `json` or `csv`


# CSRF session check

The built in Djangae checks enforce the use of session-based (rather than cookie-based) CSRF tokens. To satisfy this check
the `CSRF_USE_SESSIONS` setting must be True.

