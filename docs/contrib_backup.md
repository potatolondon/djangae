# Djangae Contrib Backup

An app to help manage datastore backups.

## Basic usage

By default all registered models are backed up to a bucket in Google Cloud Storage. Each backup is created with an enclosing directory named for the start time of the backup (this helps keep your backups organised).

* Enable datastore admin in the Cloud Console for your application.
* Add backup url to main urls.py file:
```python
    url(r'^tasks/', include('djangae.contrib.backup.urls'))
```
* Add backup entry to cron.yaml:
```yaml
cron:
- description: Scheduled datastore backups
  url: /tasks/create-datastore-backup/
  schedule: every day 07:00
```
* Define a backup queue in queue.yaml (optional, see `DJANGAE_BACKUP_QUEUE` below):
```yaml
- name: backups
  rate: 50/s
```
* Add required settings to settings.py.
```python
DJANGAE_BACKUP_ENABLED = True
```
* Add `'djangae.contrib.backup'` to `settings.INSTALLED_APPS` (if you want the tests to run).

## Other optional settings

### DJANGAE_BACKUP_GCS_BUCKET

By default backups will be created using the application's default cloud storage bucket, in a directory named "djangae-backups". If your application is named "foo-bar-baz", then the default cloud storage bucket is "foo-bar-baz.appspot.com" and backups will be created in "foo-bar-baz.appspot.com/djangae-backups".

Add `DJANGAE_BACKUP_GCS_BUCKET` to settings to change the target bucket, or to change the destination directory.

For example `DJANGAE_BACKUP_GCS_BUCKET="my-first-bucket"` would use the "my-first-bucket" cloud storage bucket for backups, and the backups would be created in the root of the bucket.


### DJANGAE_BACKUP_NAME

Set `DJANGAE_BACKUP_NAME` to a string to change the name used by the backup service to identify backups. Defaults to "djangae-backups".


### DJANGAE_BACKUP_QUEUE

Set `DJANGAE_BACKUP_QUEUE` to a string naming a queue that will be used to schedule backup tasks. The queue must be defined in your project's `queue.yaml` file. Defaults to the default App Engine queue.


### Exclude all models from certain applications:

```python
DJANGAE_BACKUP_EXCLUDE_APPS = [
    "contenttypes",
    "cspreports",
    "djangae",
    "locking",
    "osmosis",
    "sessions",
]
```


### Exclude specific models

Use the form `<app_label>_<model_name>`

```python
DJANGAE_BACKUP_EXCLUDE_MODELS = [
    'sessions_session',
]
```
