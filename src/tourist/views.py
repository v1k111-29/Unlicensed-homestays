"""Public tourist check page (M9, essentialfeatures.md T1). No login.

Privacy (AGENTS.md rule 5, D75): the page sets no cookies. The form is POST so the query
does not appear in URLs, proxy logs or browser history; CSRF is exempt because there is no
session or credential to abuse and the only effect is an anonymous count row. The template
therefore has no CSRF token, and nothing here touches the session or the messages framework.
Only the result type and time are logged (``tourist.service.record``).
"""

from __future__ import annotations

from django.conf import settings
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
    """Show the check form (GET), or run a check and show its answer (POST).

    The status code tells the browser what happened: 200 for an answer, 429 when the address
    has used its checks for the window, and 503 when no registry is loaded yet.
    """
    form = CheckForm(request.POST) if request.method == "POST" else CheckForm()
    context: dict = {"form": form, "disclaimer": NOT_FOUND_DISCLAIMER}
    status = 200
    if request.method == "POST" and form.is_valid():
        # The rate limit is checked before the registry is searched, so a flood of requests
        # cannot make the search work harder than the limit allows.
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
    # Page furniture (D94): which search mode the chips show, and real registry counts.
    # The page shows name mode when a name or locality was typed and no licence number.
    data = form.data if form.is_bound else {}
    by_name = not data.get("licence") and (data.get("name") or data.get("locality"))
    context["mode"] = "name" if by_name else "licence"
    summary = None if context.get("unavailable") else service.registry_summary()
    if summary:
        context["stats"] = {**summary, "languages": len(settings.LANGUAGES)}
    return render(request, "tourist/check.html", context, status=status)
