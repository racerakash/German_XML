from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, NameObject

from app.config import Settings
from app.errors import ServiceError
from app.models import XmlSyntax
from app.service import process_pdf

SETTINGS = Settings(
    max_pdf_bytes=2 * 1024 * 1024,
    max_xml_bytes=256 * 1024,
    max_attachment_total_bytes=2 * 1024 * 1024,
)


def test_extracts_invoice_and_other_attachments(make_pdf, cii_xml: bytes) -> None:
    pdf = make_pdf([("factur-x.xml", cii_xml), ("terms.txt", b"hello")])
    result = process_pdf(pdf, SETTINGS)
    assert result.xml_attachment.filename == "factur-x.xml"
    assert result.xml_classification.syntax is XmlSyntax.CII
    assert [(item.filename, item.content) for item in result.other_attachments] == [
        ("terms.txt", b"hello")
    ]


def test_no_xml_is_rejected(make_pdf) -> None:
    pdf = make_pdf([("notes.txt", b"not xml")])
    with pytest.raises(ServiceError) as error:
        process_pdf(pdf, SETTINGS)
    assert error.value.code == "xml_attachment_not_found"


def test_multiple_xml_attachments_are_rejected(make_pdf, cii_xml: bytes, ubl_xml: bytes) -> None:
    pdf = make_pdf([("one.xml", cii_xml), ("two.xml", ubl_xml)])
    with pytest.raises(ServiceError) as error:
        process_pdf(pdf, SETTINGS)
    assert error.value.code == "ambiguous_xml_attachments"
    assert error.value.details == {"count": 2}


def test_corrupt_pdf_is_rejected() -> None:
    with pytest.raises(ServiceError) as error:
        process_pdf(b"%PDF-1.7\nnot really a pdf", SETTINGS)
    assert error.value.code == "invalid_pdf"


def test_encrypted_pdf_is_rejected(make_pdf, cii_xml: bytes) -> None:
    pdf = make_pdf([("invoice.xml", cii_xml)], encrypt=True)
    with pytest.raises(ServiceError) as error:
        process_pdf(pdf, SETTINGS)
    assert error.value.code == "encrypted_pdf"


def test_extracts_catalog_associated_file_without_name_tree(cii_xml: bytes) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    embedded = writer.add_attachment("associated.xml", cii_xml)
    embedded.associated_file_relationship = NameObject("/Data")
    writer.root_object[NameObject("/AF")] = ArrayObject(
        [embedded.pdf_object.indirect_reference]
    )
    writer.root_object.pop(NameObject("/Names"))
    output = BytesIO()
    writer.write(output)

    result = process_pdf(output.getvalue(), SETTINGS)
    assert result.xml_attachment.filename == "associated.xml"
    assert result.xml_classification.syntax is XmlSyntax.CII


def test_duplicate_filenames_are_preserved(make_pdf, cii_xml: bytes) -> None:
    pdf = make_pdf(
        [("invoice.xml", cii_xml), ("notes.txt", b"one"), ("notes.txt", b"two")]
    )
    result = process_pdf(pdf, SETTINGS)
    assert [(item.filename, item.content) for item in result.other_attachments] == [
        ("notes.txt", b"one"),
        ("notes.txt", b"two"),
    ]


def test_total_attachment_limit_is_enforced(make_pdf, cii_xml: bytes) -> None:
    pdf = make_pdf([("invoice.xml", cii_xml), ("large.bin", b"x" * 100)])
    settings = Settings(
        max_pdf_bytes=2 * 1024 * 1024,
        max_xml_bytes=256 * 1024,
        max_attachment_total_bytes=len(cii_xml) + 50,
    )
    with pytest.raises(ServiceError) as error:
        process_pdf(pdf, settings)
    assert error.value.code == "attachments_too_large"
    assert error.value.status_code == 413
