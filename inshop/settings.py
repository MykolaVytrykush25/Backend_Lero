import json
import logging
import os
from os import environ
from pathlib import Path

from dotenv import load_dotenv
from environs import Env


load_dotenv(".env")
env = Env()

CORS_ALLOWED_ORIGIN_REGEXES = [
    '*',
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = True
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = env.str("DJANGO_SECRET_KEY")
FRONTEND_HOST = env.str("FRONTEND_HOST")
COOKIE_DOMAIN = env.str("COOKIE_DOMAIN")
DEBUG = env.bool("DEBUG_MODE")
ROOT_URLCONF = 'inshop.urls'
ALLOWED_HOSTS = ["*"]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTHENTICATION_BACKENDS = []
REST_FRAMEWORK = {
    'COMPONENT_SPLIT_REQUEST': True,
    'UNAUTHENTICATED_USER': None,
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': [],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PARSER_CLASSES": [
        'rest_framework.parsers.JSONParser',
        "rest_framework.parsers.MultiPartParser"
    ]
}
APPEND_SLASH = True
CSP_SCRIPT_SRC = ("'self'", 'ajax.googleapis.com', "'unsafe-inline'")

TEMPLATES_PATH = os.path.join(BASE_DIR, 'Templates')
AUTH_USER_MODEL = ""

WSGI_APPLICATION = 'inshop.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env.str("DB_NAME"),
        'USER': env.str("DB_USERNAME"),
        'PASSWORD': env.str("DB_PASSWORD"),
        'HOST': env.str("DB_HOST"),
        'PORT': env.str("DB_PORT"),
    }
}

INSTALLED_APPS = [
    "Users",
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "rest_framework",
    "drf_spectacular",
    "Main",
    "Proxy",
    "corsheaders",
    'django_celery_beat',
    'django_celery_results',
]


MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware'
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ["Templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


EMAIL_BACKEND = env.str("EMAIL_BACKEND")
EMAIL_HOST = env.str("EMAIL_HOST")
EMAIL_PORT = env.str("EMAIL_PORT")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS")
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL")
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD")


LOLA_HOST = env.str("LOLA_HOST")
LOLA_API_KEY = env.str("LOLA_API_KEY")
LOLA_HEADERS = {"x-api-key": LOLA_API_KEY}

GEONODE_API_KEY = env.str("GEONODE_API_KEY")
GEONODE_API_URL = env.str("GEONODE_API_URL")

RESELLER_PROXY_BASE_URL = env.str("RESELLER_PROXY_BASE_URL")
PROXY_SELLER_API_CODE = env.str("PROXY_SELLER_API_CODE")
PROXY_SELLER_API_COUPON = os.environ.get("PROXY_SELLER_API_COUPON")

PROVIDER711_API_URL = env.str("PROVIDER711_API_URL")
PROVIDER711_API_TOKEN = env.str("PROVIDER711_API_TOKEN")

DROP_PROXY_HEADER = {
    "HOST": env.str("PROXY_DROP_HOST"),
    "LEQUE-KEY-API-PUB": env.str("LEQUE_KEY_API_PUB", ""),
    "LEQUE-KEY-API-PRIV": env.str("LEQUE_KEY_API_PRIV", ""),
}
DROP_PROXY_PARAMS_GET = {"key": "bq36Nr9yNgI6RxPQA5sndUIvnowBLXPN"}
DROP_PROXY_PARAMS_ORDER = {
    "key": env.str("PROXY_DROP_ORDER_KEY"),
    "email": env.str("PROXY_DROP_EMAIL"),
    "fund": 13,
    "token_pay": env.str("PROXY_DROP_TOKEN_PAY"),
}
DROP_PROXY_BASE_URL = env.str("PROXY_DROP_BASE_URL")
DROP_PROXY_BUY_URL = env.str("PROXY_DROP_BUY_URL")
DROP_PROXY_DATA_PAY = {
    "pay": "yes",
    "email_pay": env.str("PROXY_DROP_EMAIL"),
    "token_pay": env.str("PROXY_DROP_TOKEN_PAY")
}


CRYPTOMUS_API_KEY = env.str("CRYPTOMUS_API_KEY")
CRYPTOMUS_MERCHANT = env.str("CRYPTOMUS_MERCHANT")
PAYMENT_LIFE_TIME = env.str("PAYMENT_LIFE_TIME")
CRYPTO_SECRET_KEY = env.str("CRYPTO_SECRET_KEY")
STRIPE_SECRET_ENDPOINT = env.str("STRIPE_SECRET_ENDPOINT")
STRIPE_API_KEY = env.str("STRIPE_API_KEY")


CELERY_BROKER_URL = env.str('CELERY_BROKER_REDIS_URL', 'redis://localhost:6379')
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers.DatabaseScheduler'
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True


S3_API_KEY = env.str("S3_API_KEY")
S3_SECRET_KEY = env.str("S3_SECRET_KEY")
S3_ENDPOINT = env.str("S3_ENDPOINT")
S3_BUCKET = env.str("S3_BUCKET")
S3_ACCESS_KEY = env.str("S3_ACCESS_KEY")


REFERRAL_LEVELS = [float(level) for level in os.environ.get("REFERRAL_LEVELS").split(",")]
PRODUCTS_COMMISSIONS = json.load(open("static/commissions.json"))


TG_BOT_TOKEN = env.str("TG_BOT_TOKEN")
TG_SECRET_KEY = env.str("LINK_TG_BOT_SECRET_KEY")
BOT_USERNAME = env.str("BOT_USERNAME")


GEETEST_CAPTCHA_KEY = env.str("GEETEST_CAPTCHA_KEY")
GEETEST_CAPTCHA_ID = env.str("GEETEST_CAPTCHA_ID")
GEETEST_VALIDATE_URL = env.str("GEETEST_VALIDATE_URL")
CAPTCHA_ENABLED = env.bool("CAPTCHA_ENABLED")


from django.utils.log import DEFAULT_LOGGING

DEFAULT_LOGGING['handlers']['console']['filters'] = []
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        },
    },
    'handlers': {
        'celery_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs/celery_operations.log'),
            'formatter': 'verbose',
        },
        "admin_logger": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": os.path.join(BASE_DIR, "logs/admin_operations.log"),
            "formatter": "verbose"
        }
    },
    'loggers': {
        'celery': {
            'handlers': ['celery_file'],
            'level': 'INFO',
            'propagate': True,
        },
        'admin_logger': {
            'handlers': ['admin_logger'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
logger = logging.getLogger(__name__)

import sentry_sdk

sentry_sdk.init(
    dsn="https://ab076c608a0dae03e9ba95c57c8e84ef@o4508484100685824.ingest.de.sentry.io/4508484104552528",
    traces_sample_rate=1.0,
    profiles_sample_rate=0.5,
    environment="staging",
)
