import os
import sys
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR.parent.parent / '.env')

APP_ENV = os.getenv('APP_ENV', '').strip().lower() or ('test' if 'pytest' in sys.modules or 'test' in sys.argv else '')
if APP_ENV not in {'development', 'test', 'production'}:
    raise ImproperlyConfigured('APP_ENV must explicitly be development, test, or production.')
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '').strip()
if not SECRET_KEY and APP_ENV in {'development', 'test'}:
    SECRET_KEY = 'api-gateway-explicit-nonproduction-key'
if not SECRET_KEY:
    raise ImproperlyConfigured('DJANGO_SECRET_KEY is required outside an explicit non-production profile.')
if APP_ENV == 'production' and any(marker in SECRET_KEY.lower() for marker in ('change_me', 'change-me', 'replace-with', 'django-insecure')):
    raise ImproperlyConfigured('Production DJANGO_SECRET_KEY is a placeholder.')
from bi_platform_shared.security_config import validate_production_secrets
validate_production_secrets(APP_ENV, SECRET_KEY)
if APP_ENV == 'production' and not os.getenv('DB_PASSWORD', '').strip():
    raise ImproperlyConfigured('DB_PASSWORD is required in production.')


def _env_bool(name, default=False):
    token = str(os.getenv(name, str(default))).strip().lower()
    if token in {'1', 'true', 'yes', 'on'}:
        return True
    if token in {'0', 'false', 'no', 'off'}:
        return False
    return bool(default)


def _csv_env(name, default=''):
    return [value.strip() for value in os.getenv(name, default).split(',') if value.strip()]


DEBUG = _env_bool('DEBUG', False)
ALLOWED_HOSTS = _csv_env('ALLOWED_HOSTS')
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1']
if APP_ENV == 'production' and (DEBUG or not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS):
    raise ImproperlyConfigured('Production DEBUG/ALLOWED_HOSTS configuration is unsafe.')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'gateway',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'bi_platform_shared.http.middleware.RequestIdMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'gateway.middleware.RateLimitMiddleware',
    'gateway.middleware.GatewayAuthenticationMiddleware',
    'gateway.middleware.RequestValidationMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'service_config.urls'
WSGI_APPLICATION = 'service_config.wsgi.application'
ASGI_APPLICATION = 'service_config.asgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = _csv_env('CORS_ALLOWED_ORIGINS', os.getenv('DJANGO_CORS_ALLOWED_ORIGINS', ''))
if DEBUG and not CORS_ALLOWED_ORIGINS:
    CORS_ALLOWED_ORIGINS = ['http://localhost:3000', 'http://localhost:5173', 'http://127.0.0.1:5173']
CORS_ALLOW_CREDENTIALS = bool(CORS_ALLOWED_ORIGINS)
