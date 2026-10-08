"""Public tourist check page (M9, essentialfeatures.md T1). No login.

Privacy (AGENTS.md rule 5, D75): the page sets no cookies. The form is POST so the query
does not appear in URLs, proxy logs or browser history; CSRF is exempt because there is no
session or credential to abuse and the only effect is an anonymous count row. The template
therefore has no CSRF token, and nothing here touches the session or the messages framework.
Only the result type and time are logged (``tourist.service.record``).
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from tourist import service, throttle
from tourist.forms import CheckForm
from tourist.wording import DIFFERENCE_TEXT, NOT_FOUND_DISCLAIMER


@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def check(request: HttpRequest) -> HttpResponse:
    form = CheckForm(request.POST) if request.method == "POST" else CheckForm()
    context: dict = {"form": form, "disclaimer": NOT_FOUND_DISCLAIMER}
    status = 200
    if request.method == "POST" and form.is_valid():
        if not throttle.allow(request):
            context["rate_limited"] = True
            status = 429
        else:
            try:
                result = service.check(form.query())
            except service.RegistryUnavailable:
                context["unavailable"] = True
                status = 503
            else:
                service.record(result.outcome)
                context["result"] = result
                context["differences"] = [DIFFERENCE_TEXT[d] for d in result.differences]
    return render(request, "tourist/check.html", context, status=status)
