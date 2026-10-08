"""Tourist-facing sentences that must not drift (AGENTS.md rule 2, ui-design-brief.md §10).

The "Not found" disclaimer is defined here, once, and passed to the template. Templates may
not contain the word it uses (tests/test_m6_hardening.py bans it in every template); this is
the only tourist-facing text allowed to use it. Never add "fake" or "unlicensed" to any
tourist-facing string.
"""

from django.utils.translation import gettext_lazy as _

NOT_FOUND_DISCLAIMER = _("This does not mean the stay is illegal. The registry may be incomplete.")

# What the tourist is told when an entry was found but something does not agree.
DIFFERENCE_TEXT = {
    "licence": _(
        "The licence number you entered is not in the registry, "
        "but a stay with this name and locality is."
    ),
    "name": _("The name in the registry is different from the name you entered."),
    "locality": _("The locality in the registry is different from the locality you entered."),
    "validity": _(
        "The registry entry is not valid on the date checked (expired, suspended or not yet valid)."
    ),
}
