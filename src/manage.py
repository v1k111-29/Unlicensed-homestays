#!/usr/bin/env python
"""Django's command-line entry point for Verified Stays.

Who runs it: developers and the deployment scripts, for commands such as runserver,
migrate and load_synthetic. tasks.py and scripts/dev_start.py also call it.

Key idea: this file only tells Django which settings module to use, then hands the
command line to Django. The standard Django setup is kept, so every Django command works.
"""

import os
import sys


def main() -> None:
    """Point Django at the project settings, then run the command given on the command line."""
    # setdefault keeps any value already set in the environment, so a different settings
    # module can be chosen for one command without editing this file.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # Imported here, not at the top, so that the settings module is chosen first.
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
