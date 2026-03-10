"""
Django settings for BI Voice Agent project.
"""

import os
from pathlib import Path
from datetime import timedelta

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv


load_dotenv()

# ==============================================================================
# SECURITY SETTINGS
# ==============================================================================

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-change-this-in-production-abcdefghijklmnopqrstuvwxyz1234567890')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


# ==============================================================================
# INSTALLED APPS
# ==============================================================================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',  # CORS headers for frontend integration
    
    # Local apps
    'users',
    'workspace',
    'database',
    'voice_reports',
]

# ==============================================================================
# MIDDLEWARE
# ==============================================================================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # CORS middleware (must be before CommonMiddleware)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# ==============================================================================
# URL CONFIGURATION
# ==============================================================================

ROOT_URLCONF = 'config.urls'


# ==============================================================================
# TEMPLATES
# ==============================================================================

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


# ==============================================================================
# WSGI
# ==============================================================================

WSGI_APPLICATION = 'config.wsgi.application'


# ==============================================================================
# DATABASE CONFIGURATION - POSTGRESQL
# ==============================================================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'bi_voice_agent'),
        'USER': os.environ.get('DB_USER', 'bi_admin'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'StrongPassword123'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': 600,
        'OPTIONS': {
            'connect_timeout': 10,
        }
    }
}


# ==============================================================================
# CUSTOM USER MODEL
# ==============================================================================

AUTH_USER_MODEL = 'users.User'


# ==============================================================================
# PASSWORD VALIDATION
# ==============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# ==============================================================================
# INTERNATIONALIZATION
# ==============================================================================

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# ==============================================================================
# STATIC FILES (CSS, JavaScript, Images)
# ==============================================================================

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


# ==============================================================================
# DEFAULT PRIMARY KEY FIELD TYPE
# ==============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ==============================================================================
# REST FRAMEWORK CONFIGURATION
# ==============================================================================

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'EXCEPTION_HANDLER': 'rest_framework.views.exception_handler',
}


# ==============================================================================
# JWT SETTINGS (Simple JWT)
# ==============================================================================

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    
    'JTI_CLAIM': 'jti',
}


# ==============================================================================
# EMAIL CONFIGURATION - GMAIL SMTP
# ==============================================================================

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False

# Gmail credentials from environment variables
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'Aymannk331@gmail.com')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', 'mqpuayqohmgwnzgr')
# Use friendly display name for all outgoing emails
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'BI Voice Agent <no-reply@bivoiceagent.com>')
# The actual email used for SMTP (required by Gmail)
SERVER_EMAIL = EMAIL_HOST_USER

EMAIL_TIMEOUT = 10

# Frontend URL for email verification and invitation links
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173')


# ==============================================================================
# LOGGING CONFIGURATION
# ==============================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': 'debug.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'users': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'workspace': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


# ==============================================================================
# CORS CONFIGURATION (Frontend Integration)
# ==============================================================================

# Allow CORS from frontend origins
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',      # Vite development server (default)
    'http://127.0.0.1:5173',      # Vite development server (IP)
    'http://localhost:3000',      # React/Next.js development
    'http://localhost:3001',      # Alternative frontend port
    'http://127.0.0.1:3000',
    'http://127.0.0.1:3001',
]

# Allow credentials (cookies, authorization headers)
CORS_ALLOW_CREDENTIALS = True

# Allow these HTTP methods
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# Allow these headers
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# For production, you can add additional origins via environment variable
# Example: CORS_ORIGIN_WHITELIST=https://yourdomain.com,https://www.yourdomain.com
if os.environ.get('CORS_ORIGIN_WHITELIST'):
    CORS_ALLOWED_ORIGINS.extend(
        os.environ.get('CORS_ORIGIN_WHITELIST', '').split(',')
    )


# ==============================================================================
# CLICKHOUSE CONFIGURATION
# ==============================================================================
# ==============================================================================
# CLICKHOUSE CONFIGURATION (FORCED OVERRIDE)
# ==============================================================================

CLICKHOUSE_HOST = os.getenv('CLICKHOUSE_HOST', 'localhost')

# FORCE ClickHouse HTTP port (ignore Windows env)
CLICKHOUSE_PORT = int(os.getenv('CLICKHOUSE_PORT', '8123'))
if CLICKHOUSE_PORT == 9000:
    CLICKHOUSE_PORT = 8123

CLICKHOUSE_USER = os.getenv('CLICKHOUSE_USER', 'etl_user')
CLICKHOUSE_PASSWORD = os.getenv('CLICKHOUSE_PASSWORD', 'etl_pass123')
CLICKHOUSE_DATABASE = os.getenv('CLICKHOUSE_DATABASE', 'etl')



# ==============================================================================
# ETL SERVICE CONFIGURATION
# ==============================================================================

ETL_SERVICE_URL = os.environ.get('ETL_SERVICE_URL', 'http://127.0.0.1:8001')


# ==============================================================================
# VOICE REPORTS CONFIGURATION
# ==============================================================================

# Small Whisper Service
# Use 127.0.0.1 instead of localhost to avoid DNS resolution issues
SMALL_WHISPER_URL = os.environ.get('SMALL_WHISPER_URL', 'http://127.0.0.1:8001')

# ===============================
# ClickHouse
# ===============================

CLICKHOUSE_DATABASE = os.environ.get("CLICKHOUSE_DATABASE", "default")

# ===============================
# Metabase (Self-Hosted ONLY)
# Session Auth – no Cloud, no API keys
# ===============================

METABASE_URL = os.environ.get("METABASE_URL", "http://127.0.0.1:3000")

METABASE_USERNAME = os.environ.get("METABASE_USERNAME")
METABASE_PASSWORD = os.environ.get("METABASE_PASSWORD")

if not METABASE_USERNAME or not METABASE_PASSWORD:
    raise RuntimeError(
        "METABASE_USERNAME and METABASE_PASSWORD must be set for Session Auth"
    )

# This MUST match the database ID of ClickHouse inside Metabase UI
METABASE_DATABASE_ID = int(os.environ.get("METABASE_DATABASE_ID", "2"))

# ===============================
# Optional: JWT Embedding (Self-Hosted only)
# ===============================

# Only needed if you embed dashboards/questions in an iframe
# (Admin > Settings > Embedding > Secret Key)
METABASE_SECRET_KEY = os.environ.get("METABASE_SECRET_KEY")

JWT_ISSUER = os.environ.get("JWT_ISSUER", "bi-voice-agent")
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "metabase")

# Media Files (for audio storage)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

