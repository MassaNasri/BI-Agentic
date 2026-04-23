import os
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR.parent.parent / '.env')
load_dotenv(BASE_DIR.parent.parent / '.env.microservices')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'voice-service-secret-key')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')

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
    'users',
    'workspace',
    'voice_reports',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
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

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'bi_voice_agent'),
        'USER': os.getenv('DB_USER', 'bi_admin'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'StrongPassword123'),
        'HOST': os.getenv('DB_HOST', 'postgres-voice'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': 600,
    }
}

AUTH_USER_MODEL = 'users.User'

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
        'rest_framework_simplejwt.authentication.JWTAuthentication',
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

SMALL_WHISPER_URL = os.getenv('SMALL_WHISPER_URL', 'http://ai-service:8005')
SMALL_WHISPER_HEALTH_TIMEOUT_SECONDS = int(os.getenv('SMALL_WHISPER_HEALTH_TIMEOUT_SECONDS', '5'))
SMALL_WHISPER_CONNECT_TIMEOUT_SECONDS = int(os.getenv('SMALL_WHISPER_CONNECT_TIMEOUT_SECONDS', '10'))
SMALL_WHISPER_TIMEOUT_SECONDS = int(os.getenv('SMALL_WHISPER_TIMEOUT_SECONDS', '300'))
SMALL_WHISPER_MAX_RETRIES = int(os.getenv('SMALL_WHISPER_MAX_RETRIES', '1'))
AI_SERVICE_INTERNAL_API_KEY = os.getenv('AI_SERVICE_INTERNAL_API_KEY', '')
QUERY_SERVICE_URL = os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006')
VISUALIZATION_SERVICE_URL = os.getenv('VISUALIZATION_SERVICE_URL', 'http://visualization-service:8007')
REPORT_SERVICE_URL = os.getenv('REPORT_SERVICE_URL', 'http://report-service:8003')
SUBSCRIPTION_SERVICE_URL = os.getenv('SUBSCRIPTION_SERVICE_URL', 'http://subscription-service:8008')

CLICKHOUSE_HOST = os.getenv('CLICKHOUSE_HOST', 'clickhouse')
CLICKHOUSE_PORT = int(os.getenv('CLICKHOUSE_PORT', '8123'))
CLICKHOUSE_USER = os.getenv('CLICKHOUSE_USER', 'etl_user')
CLICKHOUSE_PASSWORD = os.getenv('CLICKHOUSE_PASSWORD', 'etl_pass123')
CLICKHOUSE_DATABASE = os.getenv('CLICKHOUSE_DATABASE', 'etl')

METABASE_URL = os.getenv('METABASE_URL', 'http://metabase:3000')
METABASE_USERNAME = os.getenv('METABASE_USERNAME', '')
METABASE_PASSWORD = os.getenv('METABASE_PASSWORD', '')
METABASE_DATABASE_ID = int(os.getenv('METABASE_DATABASE_ID', '2'))
METABASE_SECRET_KEY = os.getenv('METABASE_SECRET_KEY', '')

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
