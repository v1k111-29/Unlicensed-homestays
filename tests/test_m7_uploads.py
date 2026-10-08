"""M7 uploads: preview then confirm, line-level errors, nothing saved on a bad file, the
other-district rule (D30), CSV injection, size and row limits, permissions.

All synthetic. Tests touching the database carry `django_db` (skipped without a database).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from audit.models import AuditLog
from ingest import csvtools
from ingest.csvtools import MAX_BYTES
from ingest.load import load_synthetic_set
from listings.models import Listing
from registry.models import RegistryEntry, UploadBatch

pytestmark = pytest.mark.django_db

DEV = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "out" / "dev"
LST_HEADER = "listing_id,platform,title,locality_text,pincode,district"
REG_HEADER = "licence_no,name,locality,district,valid_to,pincode"

UPLOAD = "/officer/uploads/"
CONFIRM = "/officer/uploads/confirm/"
CANCEL = "/officer/uploads/cancel/"
REG_UPLOAD = "/admin/registry/"
REG_CONFIRM = "/admin/registry/confirm/"


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def _file(data: bytes, name: str = "listings.csv") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type="text/csv")


def _listings(n: int = 3, district: str = "") -> bytes:
    rows = [f"T-{i},synthetic,Synthetic Stay {i},Ooty,643001,{district}" for i in range(1, n + 1)]
    return _csv(LST_HEADER, *rows)


def _client(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _token(response) -> str:
    match = re.search(r'name="token" value="([^"]+)"', response.content.decode())
    assert match, "no token on the preview page"
    return match.group(1)


def _saved() -> tuple[int, int, int]:
    return (
        UploadBatch.objects.count(),
        Listing.objects.count(),
        RegistryEntry.objects.count(),
    )


def _upload_audit() -> list[AuditLog]:
    return list(
        AuditLog.objects.filter(action__in=["listings_upload", "registry_upload"]).order_by("id")
    )


# ------------------------------------------------------------ preview / confirm


def test_preview_saves_nothing_and_confirm_saves_once(users, districts) -> None:
    client = _client(users["off_nil"])
    audit_before = AuditLog.objects.count()

    preview = client.post(UPLOAD, {"file": _file(_listings(3)), "dataset": ""})
    assert preview.status_code == 200
    body = preview.content.decode()
    assert "Check before saving" in body and "Not saved yet." in body
    assert "Synthetic Stay 1" in body and "Nilgiris" in body
    assert _saved() == (0, 0, 0)
    assert AuditLog.objects.count() == audit_before  # a preview is not a state change

    token = _token(preview)
    done = client.post(CONFIRM, {"token": token})
    assert done.status_code == 302 and done["Location"] == reverse("runs")
    batch = UploadBatch.objects.get()
    assert batch.type == "listings" and batch.dataset == ""
    assert batch.district == districts["nil"] and batch.uploader == users["off_nil"]
    assert batch.row_count == 3 and len(batch.file_sha256) == 64
    assert set(Listing.objects.values_list("district__name_en", flat=True)) == {"Nilgiris"}
    assert Listing.objects.filter(batch=batch).count() == 3

    [entry] = _upload_audit()
    assert entry.action == "listings_upload" and entry.actor == "officer_nil"
    assert entry.entity_id == str(batch.pk)
    assert entry.meta["sha256"] == batch.file_sha256 and entry.meta["row_count"] == 3
    assert entry.meta["district"] == "Nilgiris"

    again = client.post(CONFIRM, {"token": token}, follow=True)
    assert "expired or was already used" in again.content.decode()
    assert UploadBatch.objects.count() == 1


def test_cancel_discards_the_pending_file(users) -> None:
    client = _client(users["off_nil"])
    token = _token(client.post(UPLOAD, {"file": _file(_listings()), "dataset": ""}))
    cancelled = client.post(CANCEL, {"token": token}, follow=True)
    assert "Nothing was saved" in cancelled.content.decode()
    client.post(CONFIRM, {"token": token})
    assert _saved() == (0, 0, 0)


def test_token_of_another_user_is_refused(users) -> None:
    token = _token(
        _client(users["off_nil"]).post(UPLOAD, {"file": _file(_listings()), "dataset": ""})
    )
    other = _client(users["off_mad"]).post(CONFIRM, {"token": token}, follow=True)
    assert "expired or was already used" in other.content.decode()
    assert _saved() == (0, 0, 0)


@pytest.mark.parametrize("token", ["", "short", "../../etc", "x" * 200])
def test_malformed_tokens_are_refused(users, token: str) -> None:
    response = _client(users["off_nil"]).post(CONFIRM, {"token": token})
    assert response.status_code == 302
    assert _saved() == (0, 0, 0)


def test_same_file_cannot_be_saved_twice(users) -> None:
    client = _client(users["off_nil"])
    data = _listings()
    client.post(CONFIRM, {"token": _token(client.post(UPLOAD, {"file": _file(data)}))})
    second = client.post(UPLOAD, {"file": _file(data), "dataset": ""})
    assert second.status_code == 400
    assert "already been uploaded" in second.content.decode()
    assert UploadBatch.objects.count() == 1


def test_two_previews_of_one_file_save_once(users) -> None:
    client = _client(users["off_nil"])
    data = _listings()
    first = _token(client.post(UPLOAD, {"file": _file(data), "dataset": ""}))
    second = _token(client.post(UPLOAD, {"file": _file(data), "dataset": ""}))
    client.post(CONFIRM, {"token": first})
    response = client.post(CONFIRM, {"token": second})
    assert response.status_code == 400  # re-checked at confirm
    assert UploadBatch.objects.count() == 1 and len(_upload_audit()) == 1


# ------------------------------------------------------------ bad files save nothing


@pytest.mark.parametrize(
    ("data", "fragments"),
    [
        (_csv("platform,title", "x,y"), ["locality_text", "required column is missing"]),
        (_csv(LST_HEADER, "T-1,synthetic,Stay,Ooty,6430,"), ["<td>2</td>", "6 digits"]),
        (
            _csv(LST_HEADER, "T-1,synthetic,Stay,Ooty,643001,", "T-2,synthetic,,Ooty,643001,"),
            ["<td>3</td>", "required value is empty"],
        ),
        (_csv(LST_HEADER, "T-1,synthetic,Stay,Ooty,643001,Atlantis"), ["unknown district"]),
        (b"\xff\xfe\x00", ["UTF-8"]),
        (_csv(LST_HEADER), ["no data rows"]),
        (_csv(LST_HEADER, "a,b"), ["expected 6 cells"]),
        (_csv(LST_HEADER, "T-1,synthetic,=HYPERLINK(1),Ooty,643001,"), ["formula"]),
        (_csv(LST_HEADER, "T-1,synthetic,Stay,@SUM(A1),643001,"), ["formula"]),
        (
            _csv(LST_HEADER, "T-1,synthetic,Stay,Ooty,643001,", "T-1,synthetic,S,Ooty,643001,"),
            ["duplicate of line 2"],
        ),
    ],
)
def test_bad_csv_gives_line_errors_and_saves_nothing(users, data: bytes, fragments) -> None:
    client = _client(users["off_nil"])
    response = client.post(UPLOAD, {"file": _file(data), "dataset": ""})
    assert response.status_code == 400
    body = response.content.decode()
    assert "The file was not saved" in body
    for fragment in fragments:
        assert fragment in body
    assert 'name="token"' not in body
    assert _saved() == (0, 0, 0)
    assert _upload_audit() == []


def test_one_bad_row_rejects_the_whole_file(users) -> None:
    rows = [f"T-{i},synthetic,Stay {i},Ooty,643001," for i in range(1, 50)]
    rows.append("T-99,synthetic,Stay 99,Ooty,64300X,")
    response = _client(users["off_nil"]).post(
        UPLOAD, {"file": _file(_csv(LST_HEADER, *rows)), "dataset": ""}
    )
    assert response.status_code == 400 and "<td>51</td>" in response.content.decode()
    assert _saved() == (0, 0, 0)


def test_missing_or_empty_file_is_a_form_error(users) -> None:
    client = _client(users["off_nil"])
    response = client.post(UPLOAD, {"dataset": ""})
    assert response.status_code == 400
    assert "Choose a CSV file" in response.content.decode()
    response = client.post(UPLOAD, {"file": _file(b""), "dataset": ""})
    assert response.status_code == 400
    assert "The file is empty." in response.content.decode()
    assert _saved() == (0, 0, 0)


# ------------------------------------------------------------ size and row limits


def test_oversized_file_is_rejected_without_saving(users) -> None:
    big = _listings(1) + b"#" * (MAX_BYTES + 10)
    response = _client(users["off_nil"]).post(UPLOAD, {"file": _file(big), "dataset": ""})
    assert response.status_code == 400
    assert "larger than" in response.content.decode()
    assert _saved() == (0, 0, 0)


def test_upload_handler_keeps_at_most_the_cap_in_memory(rf) -> None:
    from ingest.views import CappedUploadHandler

    handler = CappedUploadHandler(rf.post("/"))
    handler.new_file("file", "big.csv", "text/csv", None)
    chunk = b"x" * 65536
    for start in range(0, MAX_BYTES * 2, len(chunk)):
        handler.receive_data_chunk(chunk, start)
    uploaded = handler.file_complete(0)
    assert uploaded.size >= MAX_BYTES * 2  # real size is reported
    assert len(uploaded.read()) == MAX_BYTES + 1  # but only the cap is kept


def test_too_many_rows_rejected(users, monkeypatch) -> None:
    monkeypatch.setattr(csvtools, "MAX_ROWS", 5)
    response = _client(users["off_nil"]).post(UPLOAD, {"file": _file(_listings(6)), "dataset": ""})
    assert response.status_code == 400
    assert "more than 5 data rows" in response.content.decode()
    assert _saved() == (0, 0, 0)


# ------------------------------------------------------------ district rule (D30)


def test_officer_batch_naming_another_district_is_rejected_whole_and_audited(users) -> None:
    data = _csv(
        LST_HEADER,
        "T-1,synthetic,Stay 1,Ooty,643001,Nilgiris",
        "T-2,synthetic,Stay 2,Madurai town,625001,Madurai",
        "T-3,synthetic,Stay 3,Ooty,643001,",
    )
    response = _client(users["off_nil"]).post(UPLOAD, {"file": _file(data), "dataset": ""})
    assert response.status_code == 403
    body = response.content.decode()
    assert "<td>3</td>" in body and "Madurai" in body and "rejected" in body
    assert _saved() == (0, 0, 0)
    denial = AuditLog.objects.get(action="permission_denied", entity="upload")
    assert denial.actor == "officer_nil"
    assert denial.meta["reason"] == "out_of_district"
    assert denial.meta["lines"] == [3] and denial.meta["districts"] == ["Madurai"]
    assert denial.meta["sha256"] and denial.meta["source"] == "listings.csv"


def test_officer_may_name_own_district(users, districts) -> None:
    client = _client(users["off_mad"])
    preview = client.post(UPLOAD, {"file": _file(_listings(2, "Madurai")), "dataset": ""})
    assert preview.status_code == 200
    client.post(CONFIRM, {"token": _token(preview)})
    assert UploadBatch.objects.get().district == districts["mad"]


def test_admin_listings_need_a_district_on_every_row(users) -> None:
    client = _client(users["admin"])
    response = client.post(UPLOAD, {"file": _file(_listings(2)), "dataset": ""})
    assert response.status_code == 400 and "required value is empty" in response.content.decode()
    data = _csv(
        LST_HEADER,
        "T-1,synthetic,Stay 1,Ooty,643001,Nilgiris",
        "T-2,synthetic,Stay 2,Madurai town,625001,Madurai",
    )
    preview = client.post(UPLOAD, {"file": _file(data), "dataset": ""})
    assert preview.status_code == 200
    client.post(CONFIRM, {"token": _token(preview)})
    batch = UploadBatch.objects.get()
    assert batch.district is None  # several districts (D19)
    assert sorted(Listing.objects.values_list("district__name_en", flat=True)) == [
        "Madurai",
        "Nilgiris",
    ]


# ------------------------------------------------------------ registry (admin)


def test_admin_registry_upload_preview_then_confirm(users) -> None:
    client = _client(users["admin"])
    data = _csv(
        REG_HEADER,
        "SYN-NLG-90001-A,Synthetic Lodge,Ooty,Nilgiris,2030-01-01,643001",
        "SYN-MDU-90002-B,Synthetic Inn,Madurai town,Madurai,2030-01-01,625001",
    )
    preview = client.post(REG_UPLOAD, {"file": _file(data, "registry.csv")})
    assert preview.status_code == 200 and _saved() == (0, 0, 0)
    done = client.post(REG_CONFIRM, {"token": _token(preview)})
    assert done.status_code == 302
    batch = UploadBatch.objects.get(type="registry")
    assert batch.dataset == "" and batch.district is None and batch.row_count == 2
    assert RegistryEntry.objects.filter(batch=batch).count() == 2
    [entry] = _upload_audit()
    assert entry.action == "registry_upload" and entry.meta["sha256"] == batch.file_sha256


def test_bad_registry_saves_nothing(users) -> None:
    data = _csv(REG_HEADER, "SYN-NLG-90001-A,Synthetic Lodge,Ooty,Nilgiris,01/01/2030,643001")
    response = _client(users["admin"]).post(REG_UPLOAD, {"file": _file(data)})
    assert response.status_code == 400 and "YYYY-MM-DD" in response.content.decode()
    assert _saved() == (0, 0, 0)


def test_listings_token_cannot_be_confirmed_as_registry(users) -> None:
    client = _client(users["admin"])
    data = _csv(LST_HEADER, "T-1,synthetic,Stay 1,Ooty,643001,Nilgiris")
    token = _token(client.post(UPLOAD, {"file": _file(data), "dataset": ""}))
    client.post(REG_CONFIRM, {"token": token})
    assert _saved() == (0, 0, 0)


# ------------------------------------------------------------ data sets


def test_upload_into_synthetic_dev_set_and_reserved_test_set(users) -> None:
    load_synthetic_set(DEV, "synthetic-dev", "system:test")
    client = _client(users["off_nil"])
    page = client.get(UPLOAD).content.decode()
    assert 'value="synthetic-dev"' in page and "synthetic-test" not in page
    refused = client.post(UPLOAD, {"file": _file(_listings()), "dataset": "synthetic-test"})
    assert refused.status_code == 400  # not a choice: the test set is never uploaded into
    demo = (DEV / "demo_listings.csv").read_bytes()
    preview = client.post(UPLOAD, {"file": _file(demo, "demo.csv"), "dataset": "synthetic-dev"})
    assert preview.status_code == 200
    client.post(CONFIRM, {"token": _token(preview)})
    batch = UploadBatch.objects.get(type="listings", source_name="demo.csv")
    assert batch.dataset == "synthetic-dev" and batch.row_count == 25


def test_no_registry_notice(users) -> None:
    page = _client(users["off_nil"]).get(UPLOAD).content.decode()
    assert "No registry loaded yet." in page


# ------------------------------------------------------------ permissions


@pytest.mark.parametrize(
    ("url", "role", "expected"),
    [
        (UPLOAD, "off_nil", 200),
        (UPLOAD, "admin", 200),
        (UPLOAD, "inactive", 302),  # inactive users cannot be signed in
        (REG_UPLOAD, "off_nil", 403),
        (REG_UPLOAD, "admin", 200),
    ],
)
def test_upload_page_permissions(users, url: str, role: str, expected: int) -> None:
    assert _client(users[role]).get(url).status_code == expected


@pytest.mark.parametrize("url", [UPLOAD, CONFIRM, CANCEL, REG_UPLOAD, REG_CONFIRM])
def test_anonymous_is_sent_to_login(url: str, db) -> None:
    response = Client().post(url, {"token": "x" * 40})
    assert response.status_code == 302 and "/login/" in response["Location"]
    assert _saved() == (0, 0, 0)


def test_officer_cannot_post_a_registry_file(users) -> None:
    data = _csv(REG_HEADER, "SYN-NLG-90001-A,Synthetic Lodge,Ooty,Nilgiris,2030-01-01,643001")
    response = _client(users["off_nil"]).post(REG_UPLOAD, {"file": _file(data)})
    assert response.status_code == 403
    assert _saved() == (0, 0, 0)
    assert AuditLog.objects.filter(
        action="permission_denied", actor="officer_nil", meta__reason="missing_capability"
    ).exists()


def test_officer_cannot_confirm_registry(users) -> None:
    response = _client(users["off_nil"]).post(REG_CONFIRM, {"token": "x" * 40})
    assert response.status_code == 403


def test_confirm_and_cancel_are_post_only(users) -> None:
    client = _client(users["off_nil"])
    assert client.get(CONFIRM).status_code == 405
    assert client.get(CANCEL).status_code == 405


def test_upload_enforces_csrf(users) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(users["off_nil"])
    response = client.post(UPLOAD, {"file": _file(_listings()), "dataset": ""})
    assert response.status_code == 403
    assert _saved() == (0, 0, 0)


def test_recent_uploads_are_district_scoped(users) -> None:
    nil = _client(users["off_nil"])
    nil.post(CONFIRM, {"token": _token(nil.post(UPLOAD, {"file": _file(_listings(), "nil.csv")}))})
    page = _client(users["off_mad"]).get(UPLOAD).content.decode()
    assert "nil.csv" not in page and "No files uploaded yet." in page
    assert "nil.csv" in nil.get(UPLOAD).content.decode()
