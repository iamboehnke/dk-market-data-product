"""Django uden database: API'et læser det publicerede dataprodukt (JSON) og cacher det.

Det holder appen stateless og billig (App Service F1), og det betyder, at
Azure SQL ikke vækkes fra auto-pause, hver gang nogen besøger siden.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "kun-til-lokal-udvikling")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
if os.environ.get("WEBSITE_HOSTNAME"):  # sættes automatisk af App Service
    ALLOWED_HOSTS.append(os.environ["WEBSITE_HOSTNAME"])
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1")]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "catalog",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "catalog.middleware.CorsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "catalog.context.site",
        ]},
    }
]

DATABASES = {}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "TIMEOUT": int(os.environ.get("DATA_CACHE_SECONDS", "600")),
    }
}

# Hvor dataproduktet ligger. En URL i Azure, en mappe lokalt.
DATA_BASE_URL = os.environ.get(
    "DATA_BASE_URL",
    str(BASE_DIR.parent / "pipeline" / "_local" / "public" / "kroner-og-renter" / "v1"),
)
CORS_ALLOWED_ORIGINS = [o for o in os.environ.get(
    "CORS_ALLOWED_ORIGINS", "https://mikkelbohnke.com,https://www.mikkelbohnke.com").split(",") if o]
GITHUB_REPO_URL = os.environ.get("GITHUB_REPO_URL", "https://github.com/iamboehnke/azure-kroner-og-renter")

LANGUAGE_CODE = "da"
TIME_ZONE = "Europe/Copenhagen"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
