# Djangae

**Serverless Django on Google Cloud Platform**

Djangae (djan-gee) is a Django app that allows you to run serverless Django applications on Google's Cloud Platform. It provides
everything you need to write scalable Django apps using technologies like Google Cloud Datastore, Google Cloud Tasks, and Google App Engine.

Google Group: [https://groups.google.com/forum/#!forum/djangae-users](https://groups.google.com/forum/#!forum/djangae-users)

Website: [https://djangae.org](https://djangae.org)

GitLab: [https://gitlab.com/potato-oss/djangae/djangae](https://gitlab.com/potato-oss/djangae/djangae)


## Features

* Tight integration with the [Django GCloud Connectors](https://gitlab.com/potato-oss/google-cloud/django-gcloud-connectors) sibling project, which provides an ORM backend for Google Cloud Datastore
* Django authentication backends for Google OAuth and IAP
* Easy launching and management of Google Cloud emulators for local development
* Integration with Google Cloud Tasks - easily defer functions for background processing
* Utility functions to discover information about the running environment
* A series of security patches and checks to improve the security of your project
* Test utilities for writing tests that leverage the Google Cloud Platform (e.g. task queue processing)
* Apps for cross-request locking and efficient pagination on the Google Cloud Datastore

## Supported Python & Django Versions

Djangae currently supports Django 4.2, 5.0 and 5.1, using Python 3.10+.

Support for Django 1.11 / Python 2.7 lives in the `1.x` branch.


## Supported Platforms

Djangae is primarily aimed at running applications on App Engine.
See the [Cloud Run](cloud_run.md) page for information on using it for Cloud Run.
