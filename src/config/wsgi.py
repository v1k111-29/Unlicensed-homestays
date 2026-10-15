"""WSGI entry point: the object Gunicorn loads (`config.wsgi:application`) to serve the site."""

import os

from django.core.wsgi import get_wsgi_application

# Use the production settings unless the environment names another module.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
