# Storage

Djangae provides two storage backends. `djangae.storage.CloudStorage` and `djangae.storage.BlobstoreStorage`.

If you've imported `djangae.settings_base.*`, then the default backend is `djangae.storage.CloudStorage`. If you want to configure it manually in a settings module, you can set your `DEFAULT_FILE_STORAGE` accordingly e.g. `DEFAULT_FILE_STORAGE = 'djangae.storage.CloudStorage'`.

## Cloud Storage

`djangae.storage.CloudStorage` is a  django storage backend that works with Google Cloud Storage, you can treat it just
as you would with other storage backends. Google Cloud storage is a general purpose storage backend.

To use this you need to [install the `GoogleAppEngineCloudStorageClient` library](https://cloud.google.com/appengine/docs/python/googlecloudstorageclient/using-cloud-storage#downloading_the_client_library).

* Cloud storage will use the default bucket name `CLOUD_STORAGE_BUCKET` unless specified with `BUCKET_KEY` in your settings.py

### Limitations
`djangae.storage.CloudStorage` assumes the bucket and the files to be served are public. If that's not the case, the returned file url is not accessible.

### Workaround
Before you read ahead, a few notes on this workaround:
- It hasn't been carefully tested in different browsers.
- The url doesn't work on Firefox (12.0) when using [Enhanced Tracking Protection](https://support.mozilla.org/en-US/kb/enhanced-tracking-protection-firefox-desktop)
- The url doesn't work in Safari (testd on 16.2) if `Prevent Cross-site tracking` option is enable in `Settings > Privacy`.

GCP storage has different [types of endpoints](https://cloud.google.com/storage/docs/request-endpoints).
Specifically [Authenticated browser downloads](https://cloud.google.com/storage/docs/request-endpoints) use cookie-based authentication.
Assuming the current user is authenticated with Google and has appropriate permission to download the object this URLs can be used to serve the files.

```
from djangae.contrib.common import get_request
from djangae.environment import default_gcs_bucket_name, is_production_environment

def get_authenticated_url(file):
    request = get_request()
    query_string = f"?authuser={request.user.email}" if request.user else ""
    if (is_production_environment()):
        return f"https://storage.cloud.google.com/{default_gcs_bucket_name()}/{file.name}{query_string}"
    else:
        return file.url
```

As you can see from the snippet `?authuser={request.user.email}` is added to the url. That is to handle the case where a user is signed in multiple Google accounts in the browser.

Challenges mentioned with the cookies above applies though
### Example usage

Images in this model will be publicly accessible and stored in main bucket of application.

Allowed storage permission levels are defined in [docs -  XML column](https://cloud.google.com/storage/docs/access-control?hl=en#predefined-acl).

```
from django.db import models
from djangae import fields, storage

public_storage = storage.CloudStorage(google_acl='public-read')

class Image(models.Model):
    image_file = models.ImageField(upload_to='/somewhere/', storage=public_storage)

```


## Blobstore

`djangae.storage.BlobstoreStorage` is a storage backend that uses the blobstore, this may be more suitable for temporary file needs
or file processing and is used as a proxy for serving files from Cloud Storage.
