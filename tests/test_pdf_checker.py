from __future__ import annotations

from app.config import Settings
from app.pdf_checker import check_pdf

SETTINGS = Settings(
    max_pdf_bytes=2 * 1024 * 1024,
    max_xml_bytes=256 * 1024,
    max_attachment_total_bytes=2 * 1024 * 1024,
)


def test_detects_pdfa3_zugferd_and_lists_attachment_details(
    make_pdf, cii_xml: bytes
) -> None:
    pdf = make_pdf(
        [("factur-x.xml", cii_xml), ("terms.txt", b"terms")],
        pdfa_part="3",
        pdfa_conformance="B",
        relationships={"factur-x.xml": "Alternative", "terms.txt": "Supplement"},
    )

    result = check_pdf(pdf, SETTINGS)

    assert result.is_pdfa3_or_zugferd_with_xml is True
    assert result.is_pdfa3 is True
    assert result.pdfa_part == "3"
    assert result.pdfa_conformance == "B"
    assert result.has_xml_attachment is True
    assert result.is_zugferd is True
    assert [(item.filename, item.attachment_type) for item in result.attachments] == [
        ("factur-x.xml", "CII"),
        ("terms.txt", "OTHER"),
    ]
    assert result.attachments[0].association_relationship == "Alternative"
    assert result.attachments[0].classification is not None
    assert result.attachments[0].classification.standard.value == "ZUGFERD_FACTUR_X"


def test_pdfa3_without_xml_does_not_match(make_pdf) -> None:
    pdf = make_pdf([("terms.txt", b"terms")], pdfa_part="3")
    result = check_pdf(pdf, SETTINGS)
    assert result.is_pdfa3 is True
    assert result.has_xml_attachment is False
    assert result.is_pdfa3_or_zugferd_with_xml is False


def test_zugferd_xml_matches_even_without_pdfa3_claim(make_pdf, cii_xml: bytes) -> None:
    result = check_pdf(make_pdf([("factur-x.xml", cii_xml)]), SETTINGS)
    assert result.is_pdfa3 is False
    assert result.is_zugferd is True
    assert result.is_pdfa3_or_zugferd_with_xml is True


def test_xrechnung_xml_is_reported_but_not_zugferd(make_pdf, ubl_xml: bytes) -> None:
    result = check_pdf(make_pdf([("xrechnung.xml", ubl_xml)]), SETTINGS)
    assert result.has_xml_attachment is True
    assert result.is_zugferd is False
    assert result.is_pdfa3_or_zugferd_with_xml is False
    assert result.attachments[0].attachment_type == "UBL"


def test_malformed_xml_is_listed_without_rejecting_pdf(make_pdf) -> None:
    result = check_pdf(make_pdf([("broken.xml", b"<Invoice>")]), SETTINGS)
    assert result.has_xml_attachment is True
    assert result.is_zugferd is False
    assert result.attachments[0].attachment_type == "XML"
    assert result.attachments[0].classification is None
