import sys


def test_python_is_3_11() -> None:
    assert sys.version_info[:2] == (3, 11)


def test_stack_libraries_import() -> None:
    import argon2  # noqa: F401
    import django  # noqa: F401
    import indic_transliteration  # noqa: F401
    import psycopg  # noqa: F401
    import rapidfuzz  # noqa: F401
    import whitenoise  # noqa: F401

    assert django.VERSION[:2] >= (5, 2) and django.VERSION[0] < 6
