import os
import sys
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR.parent.parent / '.env')
load_dotenv(BASE_DIR.parent.parent / '.env')

APP_ENV = os.getenv('APP_ENV', '').strip().lower() or ('test' if 'pytest' in sys.modules or 'test' in sys.argv else '')
if APP_ENV not in {'development', 'test', 'production'}:
    raise ImproperlyConfigured('APP_ENV must explicitly be development, test, or production.')
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '').strip()
if not SECRET_KEY and APP_ENV in {'development', 'test'}:
    SECRET_KEY = 'subscription-service-explicit-nonproduction-key'
if not SECRET_KEY:
    raise ImproperlyConfigured('DJANGO_SECRET_KEY is required outside an explicit non-production profile.')
if APP_ENV == 'production' and any(marker in SECRET_KEY.lower() for marker in ('change_me', 'change-me', 'replace-with', 'django-insecure')):
    raise ImproperlyConfigured('Production DJANGO_SECRET_KEY is a placeholder.')
from bi_platform_shared.security_config import validate_production_secrets
validate_production_secrets(APP_ENV, SECRET_KEY)
if APP_ENV == 'production' and not os.getenv('DB_PASSWORD', '').strip():
    raise ImproperlyConfigured('DB_PASSWORD is required in production.')

# A real payment provider is not integrated. Paid activation is disabled by
# default; the sandbox is only for explicit local/test use.
PAYMENT_MODE = os.getenv('PAYMENT_MODE', 'disabled').strip().lower()
if PAYMENT_MODE not in {'disabled', 'sandbox'}:
    raise ImproperlyConfigured('PAYMENT_MODE must be disabled or sandbox.')
if APP_ENV == 'production' and PAYMENT_MODE != 'disabled':
    raise ImproperlyConfigured('Production payment simulation is forbidden.')
if APP_ENV == 'production' and (
    len(SECRET_KEY) < 32 or SECRET_KEY.lower() in {'password', 'admin', 'changeme', 'secret', '123456'}
    or os.getenv('DB_PASSWORD', '').strip().lower() in {'password', 'admin', 'changeme', 'secret', '123456'}
):
    raise ImproperlyConfigured('Production security credentials are weak or placeholders.')


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
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'subscription',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'bi_platform_shared.http.middleware.RequestIdMiddleware',
    'corsheaders.middleware.CorsMiddleware',
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

if APP_ENV == 'test':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'bi_voice_agent'),
            'USER': os.getenv('DB_USER', 'bi_admin'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'postgres-subscription'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 600,
        }
    }

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'subscription.authentication.SubscriptionJWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

FREE_TIER_VOICE_REQUEST_LIMIT = int(os.getenv('FREE_TIER_VOICE_REQUEST_LIMIT', '3'))
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', '').strip().lower()
ADMIN_NAME = os.getenv('ADMIN_NAME', 'System Admin')
SYSTEM_ADMIN_USER_ID = int(os.getenv('SYSTEM_ADMIN_USER_ID', '0'))

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = _csv_env('CORS_ALLOWED_ORIGINS', os.getenv('DJANGO_CORS_ALLOWED_ORIGINS', ''))
if DEBUG and not CORS_ALLOWED_ORIGINS:
    CORS_ALLOWED_ORIGINS = ['http://localhost:3000', 'http://localhost:5173', 'http://127.0.0.1:5173']
CORS_ALLOW_CREDENTIALS = bool(CORS_ALLOWED_ORIGINS)
