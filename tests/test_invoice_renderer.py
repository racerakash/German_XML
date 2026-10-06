from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.cli import main
from app.errors import ServiceError
from app.invoice_types import DOCUMENT_TYPE_TITLES, invoice_title
from app.invoice_renderer import render_invoice_pdf
from app.models import XmlSyntax


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_renders_polished_ubl_invoice_with_appendix(rich_ubl_xml: bytes) -> None:
    pdf_bytes, classification = render_invoice_pdf(rich_ubl_xml)
    reader = PdfReader(BytesIO(pdf_bytes))
    text = _pdf_text(pdf_bytes)

    assert pdf_bytes.startswith(b"%PDF-")
    assert classification.syntax is XmlSyntax.UBL
    assert len(reader.pages) >= 2
    assert "INVOICE" in text
    assert "UBL-2026-0042" in text
    assert "Seller GmbH" in text
    assert "Buyer AG" in text
    assert "Consulting package" in text
    assert "Payable amount" in text
    assert "Complete XML data appendix" in text
    assert "Research & Development / Muenchen" in text
    assert hashlib.sha256(b"hello").hexdigest() in text.replace("\n", "")
    assert "aGVsbG8=" not in text
    assert not reader.attachments


def test_renders_cii_invoice_and_unmapped_data(rich_cii_xml: bytes) -> None:
    pdf_bytes, classification = render_invoice_pdf(rich_cii_xml)
    text = _pdf_text(pdf_bytes)

    assert classification.syntax is XmlSyntax.CII
    assert "CII-2026-0007" in text
    assert "CII Seller GmbH" in text
    assert "Engineering service" in text
    assert "595.00 EUR" in text
    assert "UNMAPPED-CII-ACCOUNT" in text


def test_renders_ubl_credit_note(ubl_credit_note_xml: bytes) -> None:
    pdf_bytes, classification = render_invoice_pdf(ubl_credit_note_xml)
    text = _pdf_text(pdf_bytes)

    assert classification.syntax is XmlSyntax.UBL
    assert "CREDIT NOTE" in text
    assert "CN-9" in text
    assert "Returned item" in text
    assert "1 C62" in text


@pytest.mark.parametrize(
    ("root_name", "type_element", "type_code", "line_name", "quantity_name", "expected_title"),
    [
        ("Invoice", "InvoiceTypeCode", "386", "InvoiceLine", "InvoicedQuantity", "PREPAYMENT INVOICE"),
        ("CreditNote", "CreditNoteTypeCode", "381", "CreditNoteLine", "CreditedQuantity", "CREDIT NOTE"),
        ("DebitNote", "DebitNoteTypeCode", "383", "DebitNoteLine", "DebitedQuantity", "DEBIT NOTE"),
        ("SelfBilledInvoice", "InvoiceTypeCode", "389", "InvoiceLine", "InvoicedQuantity", "SELF-BILLED INVOICE"),
        (
            "SelfBilledCreditNote",
            "CreditNoteTypeCode",
            "261",
            "CreditNoteLine",
            "CreditedQuantity",
            "SELF-BILLED CREDIT NOTE",
        ),
    ],
)
def test_renders_all_ubl_invoice_family_roots(
    root_name: str,
    type_element: str,
    type_code: str,
    line_name: str,
    quantity_name: str,
    expected_title: str,
) -> None:
    namespace = f"urn:oasis:names:specification:ubl:schema:xsd:{root_name}-2"
    total_name = "RequestedMonetaryTotal" if root_name == "DebitNote" else "LegalMonetaryTotal"
    xml = f"""<{root_name} xmlns="{namespace}"
      xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
      xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
      <cbc:ID>{root_name}-42</cbc:ID><cbc:{type_element}>{type_code}</cbc:{type_element}>
      <cac:{line_name}><cbc:ID>1</cbc:ID><cbc:{quantity_name} unitCode="C62">2</cbc:{quantity_name}>
        <cbc:LineExtensionAmount currencyID="EUR">20.00</cbc:LineExtensionAmount>
        <cac:Item><cbc:Name>Universal line</cbc:Name></cac:Item>
        <cac:Price><cbc:PriceAmount currencyID="EUR">10.00</cbc:PriceAmount></cac:Price>
      </cac:{line_name}>
      <cac:{total_name}><cbc:PayableAmount currencyID="EUR">20.00</cbc:PayableAmount></cac:{total_name}>
    </{root_name}>""".encode()

    pdf_bytes, classification = render_invoice_pdf(xml)
    text = _pdf_text(pdf_bytes)

    assert classification.document_type == root_name
    assert expected_title in text
    assert "Universal line" in text
    assert "2 C62" in text
    assert "20.00 EUR" in text


@pytest.mark.parametrize("type_code, expected_title", sorted(DOCUMENT_TYPE_TITLES.items()))
def test_all_known_invoice_type_codes_have_titles(type_code: str, expected_title: str) -> None:
    assert invoice_title(type_code, "CrossIndustryInvoice") == expected_title


def test_unknown_invoice_type_code_is_renderable_and_visible() -> None:
    assert invoice_title("999", "Invoice") == "INVOICE (TYPE 999)"


def test_many_lines_create_valid_multipage_pdf(rich_ubl_xml: bytes) -> None:
    xml_text = rich_ubl_xml.decode("utf-8")
    start = xml_text.index("<cac:InvoiceLine>")
    end = xml_text.index("</cac:InvoiceLine>", start) + len("</cac:InvoiceLine>")
    line = xml_text[start:end]
    expanded = (xml_text[:start] + line * 45 + xml_text[end:]).encode("utf-8")

    pdf_bytes, _ = render_invoice_pdf(expanded)
    reader = PdfReader(BytesIO(pdf_bytes))
    assert len(reader.pages) >= 4
    assert all((page.extract_text() or "").strip() for page in reader.pages)


def test_unknown_xml_is_rejected() -> None:
    with pytest.raises(ServiceError) as error:
        render_invoice_pdf(b"<root><value>1</value></root>")
    assert error.value.code == "unsupported_xml_syntax"


def test_cli_renders_pdf(
    tmp_path: Path, rich_cii_xml: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "invoice.xml"
    output = tmp_path / "nested" / "invoice.pdf"
    source.write_bytes(rich_cii_xml)

    assert main(["render-pdf", str(source), "--output", str(output)]) == 0
    assert output.read_bytes().startswith(b"%PDF-")
    captured = capsys.readouterr()
    assert "syntax=CII" in captured.out
    assert f"saved={output}" in captured.out


def test_cli_render_write_failure(
    tmp_path: Path, rich_ubl_xml: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "invoice.xml"
    source.write_bytes(rich_ubl_xml)
    directory_target = tmp_path / "already-a-directory"
    directory_target.mkdir()

    assert main(["render-pdf", str(source), "--output", str(directory_target)]) == 1
    assert "outcome=error" in capsys.readouterr().err


def test_pdf_bytes_can_round_trip_through_base64(rich_ubl_xml: bytes) -> None:
    pdf_bytes, _ = render_invoice_pdf(rich_ubl_xml)
    assert base64.b64decode(base64.b64encode(pdf_bytes)) == pdf_bytes
