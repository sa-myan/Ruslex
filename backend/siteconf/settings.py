"""Deployment settings. Nothing here reads the database at import time."""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [part.strip() for part in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if part.strip()]
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "").rstrip("/")
CSRF_TRUSTED_ORIGINS = [PUBLIC_ORIGIN] if PUBLIC_ORIGIN else []

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "accounts", "dictionary",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "siteconf.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug", "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "siteconf.wsgi.application"
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
LEXICON_DB = DATA_DIR / "lexicon" / "lexicon.db"
ADMIN_DB = DATA_DIR / "admin" / "admin.sqlite3"
if LEXICON_DB.resolve() == ADMIN_DB.resolve():
    raise RuntimeError("Authentication and lexicon databases MUST be different")
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ADMIN_DB, "OPTIONS": {"timeout": 30}},
    "lexicon": {"ENGINE": "django.db.backends.sqlite3", "NAME": LEXICON_DB, "OPTIONS": {"timeout": 30}},
}
DATABASE_ROUTERS = ["siteconf.router.DatabaseRouter"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = os.environ.get("HTTPS_ENABLED", "1") == "1"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "collected_static"
STATICFILES_DIRS = [BASE_DIR / "frontend_static"]
STORAGES = {"staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
