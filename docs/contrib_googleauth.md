
# Googleauth (djangae.contrib.googleauth)

Djangae comes with a built-in Django application for handling Google Cloud authentication for you. `djangae.contrib.googleauth`
provides Django authentication backends and utilities for handling authentication and authorization using Google Internet Aware Proxy
(IAP), and also through Google's OAuth2 service.

googleauth gives an authentication system very similar to the built-in contrib.auth that comes with Django. The differences
are as follows:

 - Provides backends for Google Cloud authentication systems
 - Built for the Google Cloud Datastore rather than SQL
 - Permissions are not stored in the database, but are instead generated from apps + models. This avoids M2M relationships
   that wouldn't work well on the Datastore, but sacrifices the ability to create Permissions dynamically.


## Installation and Configuration

The googleauth app ships with two different authentication backends:

 1. An IAP backend which uses Google's Internet Aware Proxy to login users who have hit a service that's restricted by IAP
 2. An OAuth2 backend which uses Google's oauth implementation

You can use these backends individually, or in combination. If you use the backends in combination then IAP would be responsible
for authentication (unless you're on a non-IAP protected service), and then OAuth can be used for authorization with additional scopes.

As an example, if you hit an IAP protected view, with `@login_required` for example, then the user will be authenticated using IAP.

However, when you make use of the `@oauth_scopes_required(scopes, offline=False)` decorator, then an oauth flow will be triggered. Whether the view
is IAP protected, or not, this will result in the user authenticating and authorizing with OAuth. This will only happen if the user hasn't
already granted the required scopes.

The first place to configure then is your `AUTHENTICATION_BACKENDS` setting:

```python
AUTHENTICATION_BACKENDS = (
    "djangae.contrib.googleauth.backends.iap.IAPBackend",
    "djangae.contrib.googleauth.backends.oauth2.OAuthBackend",
)
```

And then you must add `djangae.contrib.googleauth` to your `INSTALLED_APPS` setting, and add the authentication middleware. e.g.

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'djangae.contrib.googleauth.middleware.AuthenticationMiddleware', # <--
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

You must also have `django.contrib.contenttypes`, and `django.contrib.auth` in your `INSTALLED_APPS` for everything to function correctly.

Finally, you must include the `googleauth` urls in your urlpatterns:

```python
urlpatterns = [
    ...
    path('googleauth/', include('djangae.contrib.googleauth.urls')),
]
```

### Custom User model

Like Django's auth app, googleauth ships a concrete `User` model which you an use directly. However, if you want to customise this, you should
instead inherit from `AbstractGoogleUser`. This includes all the fields necessary for the googleauth authentication backends, but is an abstract
model and so avoids multi-table inheritance.

### Custom Permissions

By default the generated permissions are the standard add, change, delete, and view permissions that Django's auth system
defines. However you can add additional permissions to this on a per-app-model basis or globally by using the `GOOGLEAUTH_CUSTOM_PERMISSIONS`
setting in your settings.py

```python
GOOGLEAUTH_CUSTOM_PERMISSIONS = {
    '__all__': ['archive'],
    'events.Event': ['invite']
}
```

### OAuth 2.0 Configuration

IAP requires little configuration, but OAuth 2.0 unfortunately requires a bit more. To start with you have the `GOOGLEAUTH_OAUTH_SCOPES` setting. This
is the list of default scopes that your application asks for when the user is required to login. The default setting is:

```python
GOOGLEAUTH_OAUTH_SCOPES = [
    "openid",
    "profile",
    "email"
]
```

But you can replace this list to request more account access.

Next you must configure your client ID and client secret:

```python
GOOGLEAUTH_CLIENT_ID = "..."
GOOGLEAUTH_CLIENT_SECRET = "..."
```

You must generate these values in the Google Cloud Console.

When you configure OAuth Consent Screen and Credentials on Google Cloud Platform you are
required to configure a list of Authorised domains and OAuth redirects.

### Linking OAuth & Django Session Expiry

By default, an oauth session expiring doesn't force log-out the user from their Django session. If however you want to *require* that a Django session
expires when the oauth session expires, you can do so by setting the `GOOGLEAUTH_LINK_OAUTH_SESSION_EXPIRY` setting to `True`. This will redirect the user back through the oauth flow (although normally transparently).

### Handling App Engine Versioning

While working on multiple AppEngine versions it's quite inconvenient to have to update those lists for every new version you deploy.
In order to workaround the problem we've added the `GOOGLEAUTH_OAUTH_REDIRECT_HOST` setting.
If provided, the user will automatically be redirected to the configured base url during the OAuth2 flow (independently from which application version the flow is triggered from).
The `oauth2callback` will automatically redirect the user back to the right application version that triggered the flow.

ie.
```python
GOOGLEAUTH_OAUTH_REDIRECT_HOST = "app.appspot.com"
```

Finally, you'll probably want to set your `LOGIN_URL` setting to the oauth_login view which will trigger the oauth
authentication if necessary:

```python
LOGIN_URL = reverse_lazy('oauth_login')
```

### IAP configuration
IAP uses JSON Web Tokens (JWT) to make sure that a request to your app is authorized. This protects your app from the following kind of risks:

- IAP is accidentally disabled;
- Misconfigured firewalls;
- Access from within the project.
- Attackers bypasses IAP unsigned identity headers.

One of the constraints of the validation is the audience should match the `Signed Header JWT Audience` of your project.

To get audience string values from the Cloud Console, go to the [Identity-Aware Proxy settings](https://console.cloud.google.com/security/iap/?_ga=2.175450922.908770789.1613644087-688439372.1485967413) for your project, click **More** next to the Load Balancer resource, and then select **Signed Header JWT Audience**. The Signed Header JWT dialog that appears displays the aud claim for the selected resource.

In order to use IAP backend you need to set `GOOGLEAUTH_IAP_JWT_AUDIENCE` in your settings using this string.

Please refer to this [page](https://cloud.google.com/iap/docs/signed-headers-howto#verifying_the_jwt_header) for more context.

The JWT audience is used to check that the IAP headers haven't been tampered with. If you are testing
locally then you can disable the JWT checking by setting the `GOOGLEAUTH_IAP_JWT_ENABLED` setting
to `False`. It is highly recommended to keep this setting to `True` on production!

## Testing Authentication Locally

googleauth ships with a middleware class that simulates IAP authentication.

Adding `djangae.contrib.googleauth.middleware.LocalIAPLoginMiddleware` to your `MIDDLEWARE` setting will give the following
features:

 - Visiting `/_dj/login/` will give you a login view to set which account to simulate. IAP credentials will then reflect this login
 - Visiting `/_dj/logout/` will remove the IAP credentials

The middleware will not run if djangae.environment reports that the site is on production. It is highly recommended that you
don't include this middleware in live production settings.
