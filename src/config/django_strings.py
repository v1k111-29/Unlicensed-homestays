"""Django's own messages that can appear on our core screens but have no Tamil translation in
Django's bundled catalog. Listing them here with gettext_noop puts them into our catalog
(``src/locale/ta``), which takes precedence over Django's (LOCALE_PATHS). The msgids must stay
byte-identical to Django's. Nothing imports this module; it exists for extraction only.
"""

from django.utils.translation import gettext_noop

DJANGO_MESSAGES = [
    # django.contrib.auth.forms.AuthenticationForm (login page)
    gettext_noop(
        "Please enter a correct %(username)s and password. Note that both fields may be "
        "case-sensitive."
    ),
    # django.forms.ModelChoiceField (tourist district, upload data set)
    gettext_noop("Select a valid choice. That choice is not one of the available choices."),
    gettext_noop("Select a valid choice. %(value)s is not one of the available choices."),
]
