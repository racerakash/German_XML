from __future__ import annotations

import base64
import hashlib
from uuid import UUID


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def test_health(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    UUID(response.headers["X-Request-ID"])


def test_xml_endpoint_returns_identifier_and_classification(client, ubl_xml: bytes, caplog) -> None:
    with caplog.at_level("INFO", logger="uvicorn.error"):
        response = client.post(
            "/v1/xml/identify",
            json={"content_base64": _b64(ubl_xml), "filename": "invoice.xml"},
        )
    assert response.status_code == 200
    body = response.json()
    UUID(body["identifier"])
    assert response.headers["X-Request-ID"] == body["identifier"]
    assert body["classification"]["syntax"] == "UBL"
    assert body["classification"]["standard"] == "XRECHNUNG"
    assert body["sha256"] == hashlib.sha256(ubl_xml).hexdigest()
    assert _b64(ubl_xml) not in caplog.text
    assert f"request_id={body['identifier']}" in caplog.text
    assert "xml_syntax=UBL" in caplog.text


def test_pdf_endpoint_returns_original_pdf_and_split_files(client, make_pdf, cii_xml: bytes) -> None:
    pdf = make_pdf([("factur-x.xml", cii_xml), ("readme.txt", b"terms")])
    response = client.post(
        "/v1/pdf/extract",
        json={"content_base64": _b64(pdf), "filename": "source.pdf"},
    )
    assert response.status_code == 200
    body = response.json()
    assert base64.b64decode(body["pdf"]["content_base64"]) == pdf
    assert base64.b64decode(body["xml"]["content_base64"]) == cii_xml
    assert body["xml"]["classification"]["syntax"] == "CII"
    assert body["attachments"][0]["filename"] == "readme.txt"
    assert base64.b64decode(body["attachments"][0]["content_base64"]) == b"terms"


def test_pdf_endpoint_rejects_multiple_xml_with_identifier(
    client, make_pdf, cii_xml: bytes, ubl_xml: bytes
) -> None:
    pdf = make_pdf([("one.xml", cii_xml), ("two.xml", ubl_xml)])
    response = client.post(
        "/v1/pdf/extract", json={"content_base64": _b64(pdf)}
    )
    assert response.status_code == 422
    body = response.json()
    UUID(body["identifier"])
    assert body["error"]["code"] == "ambiguous_xml_attachments"
    assert body["error"]["details"] == {"count": 2}


def test_pdf_check_endpoint_returns_flags_and_attachment_types(
    client, make_pdf, cii_xml: bytes, caplog
) -> None:
    pdf = make_pdf(
        [("factur-x.xml", cii_xml), ("readme.txt", b"terms")],
        pdfa_part="3",
        relationships={"factur-x.xml": "Alternative"},
    )
    with caplog.at_level("INFO", logger="uvicorn.error"):
        response = client.post(
            "/v1/pdf/check",
            json={"content_base64": _b64(pdf), "filename": "hybrid.pdf"},
        )

    assert response.status_code == 200
    body = response.json()
    UUID(body["identifier"])
    assert response.headers["X-Request-ID"] == body["identifier"]
    assert body["filename"] == "hybrid.pdf"
    assert body["is_pdfa3_or_zugferd_with_xml"] is True
    assert body["is_pdfa3"] is True
    assert body["pdfa_part"] == "3"
    assert body["pdfa_conformance"] == "B"
    assert body["pdfa_detection"] == "XMP_METADATA_CLAIM"
    assert body["has_xml_attachment"] is True
    assert body["is_zugferd"] is True
    assert [(item["filename"], item["attachment_type"]) for item in body["attachments"]] == [
        ("factur-x.xml", "CII"),
        ("readme.txt", "OTHER"),
    ]
    assert body["attachments"][0]["association_relationship"] == "Alternative"
    assert "content_base64" not in body["attachments"][0]
    assert "xml_syntax=CII" in caplog.text


def test_pdf_check_endpoint_returns_false_for_plain_pdf(client, make_pdf) -> None:
    response = client.post(
        "/v1/pdf/check",
        json={"content_base64": _b64(make_pdf([("notes.txt", b"hello")]))},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_pdfa3_or_zugferd_with_xml"] is False
    assert body["is_pdfa3"] is False
    assert body["has_xml_attachment"] is False
    assert body["is_zugferd"] is False


def test_render_pdf_endpoint_returns_base64_pdf(
    client, rich_ubl_xml: bytes, caplog
) -> None:
    with caplog.at_level("INFO", logger="uvicorn.error"):
        response = client.post(
            "/v1/xml/render-pdf",
            json={"content_base64": _b64(rich_ubl_xml), "filename": "source.invoice.xml"},
        )
    assert response.status_code == 200
    body = response.json()
    UUID(body["identifier"])
    assert response.headers["X-Request-ID"] == body["identifier"]
    assert body["classification"]["syntax"] == "UBL"
    assert body["pdf"]["filename"] == "source.invoice.pdf"
    pdf_bytes = base64.b64decode(body["pdf"]["content_base64"])
    assert pdf_bytes.startswith(b"%PDF-")
    assert body["pdf"]["size_bytes"] == len(pdf_bytes)
    assert body["pdf"]["sha256"] == hashlib.sha256(pdf_bytes).hexdigest()
    assert "xml_syntax=UBL" in caplog.text


def test_render_pdf_endpoint_rejects_unknown_xml(client) -> None:
    response = client.post(
        "/v1/xml/render-pdf", json={"content_base64": _b64(b"<root />")}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_xml_syntax"


def test_invalid_base64_uses_consistent_error_envelope(client) -> None:
    response = client.post(
        "/v1/xml/identify", json={"content_base64": "not base64***"}
    )
    assert response.status_code == 422
    body = response.json()
    UUID(body["identifier"])
    assert body["error"]["code"] == "invalid_base64"
    assert response.headers["X-Request-ID"] == body["identifier"]


def test_unknown_xml_returns_200(client) -> None:
    response = client.post(
        "/v1/xml/identify", json={"content_base64": _b64(b"<hello />")}
    )
    assert response.status_code == 200
    assert response.json()["classification"]["syntax"] == "UNKNOWN"


def test_request_validation_error_does_not_echo_input(client) -> None:
    response = client.post("/v1/xml/identify", json={"unexpected": "secret"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "secret" not in response.text


def test_payload_limit_returns_413(make_pdf, cii_xml: bytes) -> None:
    from fastapi.testclient import TestClient

    from app.api import create_app
    from app.config import Settings

    client = TestClient(
        create_app(Settings(max_pdf_bytes=10, max_xml_bytes=10, max_attachment_total_bytes=10))
    )
    response = client.post(
        "/v1/xml/identify", json={"content_base64": _b64(b"<root>too large</root>")}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
