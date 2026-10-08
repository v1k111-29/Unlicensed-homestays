from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.models import District
from tourist.service import Query


class CheckForm(forms.Form):
    """Licence number, or name + locality; district optional (essentialfeatures.md T1).
    No field is required by the browser; ``clean`` decides which combination is enough."""

    licence = forms.CharField(label=_("Licence number"), max_length=64, required=False)
    name = forms.CharField(label=_("Name of the stay"), max_length=200, required=False)
    locality = forms.CharField(label=_("Locality (town or area)"), max_length=200, required=False)
    district = forms.ModelChoiceField(
        label=_("District"),
        queryset=District.objects.order_by("name_en"),
        required=False,
        empty_label=_("All districts"),
    )

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        licence, name, locality = (data.get(k, "") or "" for k in ("licence", "name", "locality"))
        if licence:
            return data
        if name and not locality:
            self.add_error("locality", _("Enter the locality of the stay, or a licence number."))
        elif locality and not name:
            self.add_error("name", _("Enter the name of the stay, or a licence number."))
        elif not name and not locality:
            raise forms.ValidationError(
                _("Enter a licence number, or the name of the stay and its locality."),
                code="empty",
            )
        return data

    def query(self) -> Query:
        d = self.cleaned_data
        district = d.get("district")
        return Query(
            licence=d.get("licence", ""),
            name=d.get("name", ""),
            locality=d.get("locality", ""),
            district_id=district.pk if district else None,
        )
