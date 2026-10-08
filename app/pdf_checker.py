from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

from app.config import Settings
from app.encoding import sha256_hex
from app.errors import ServiceError
from app.models import InvoiceStandard, XmlClassification, XmlSyntax
from app.pdf_extractor import ExtractedAttachment, extract_attachments, looks_like_xml
from app.xml_identifier import identify_xml


@dataclass(frozen=True, slots=True)
class CheckedAttachment:
    filename: str
    media_type: str
    attachment_type: str
    association_relationship: str | None
    size_bytes: int
    sha256: str
    classification: XmlClassification | None


@dataclass(frozen=True, slots=True)
class PdfCheckResult:
    is_pdfa3_or_zugferd_with_xml: bool
    is_pdfa3: bool
    pdfa_part: str | None
    pdfa_conformance: str | None
    has_xml_attachment: bool
    is_zugferd: bool
    attachments: list[CheckedAttachment]


def _pdfa_claim(pdf_bytes: bytes) -> tuple[str | None, str | None]:
    """Read the document's PDF/A identification claim from XMP metadata.

    This intentionally does not claim full ISO 19005 validation. A dedicated
    validator such as veraPDF is required to prove PDF/A conformance.
    """
    try:
        xmp = PdfReader(BytesIO(pdf_bytes), strict=False).xmp_metadata
        if xmp is None:
            return None, None
        part = xmp.pdfaid_part
        conformance = xmp.pdfaid_conformance
        return (
            str(part).strip() if part is not None else None,
            str(conformance).strip().upper() if conformance is not None else None,
        )
    except Exception:
        # Invalid PDF structure and encryption are rejected by extract_attachments
        # before this helper runs. Broken or absent XMP simply means no claim.
        return None, None


def _check_attachment(
    attachment: ExtractedAttachment, settings: Settings
) -> CheckedAttachment:
    classification: XmlClassification | None = None
    attachment_type = "OTHER"
    if looks_like_xml(attachment):
        attachment_type = "XML"
        if len(attachment.content) <= settings.max_xml_bytes:
            try:
                classification = identify_xml(attachment.content)
            except ServiceError:
                classification = None
            else:
                if classification.syntax is not XmlSyntax.UNKNOWN:
                    attachment_type = classification.syntax.value

    return CheckedAttachment(
        filename=attachment.filename,
        media_type=attachment.media_type,
        attachment_type=attachment_type,
        association_relationship=attachment.association_relationship,
        size_bytes=len(attachment.content),
        sha256=sha256_hex(attachment.content),
        classification=classification,
    )


def check_pdf(pdf_bytes: bytes, settings: Settings) -> PdfCheckResult:
    attachments = extract_attachments(
        pdf_bytes, max_total_bytes=settings.max_attachment_total_bytes
    )
    checked = [_check_attachment(attachment, settings) for attachment in attachments]

    pdfa_part, pdfa_conformance = _pdfa_claim(pdf_bytes)
    is_pdfa3 = pdfa_part == "3"
    has_xml = any(item.attachment_type in {"XML", "CII", "UBL"} for item in checked)
    is_zugferd = any(
        item.classification is not None
        and item.classification.standard is InvoiceStandard.ZUGFERD_FACTUR_X
        for item in checked
    )

    return PdfCheckResult(
        is_pdfa3_or_zugferd_with_xml=has_xml and (is_pdfa3 or is_zugferd),
        is_pdfa3=is_pdfa3,
        pdfa_part=pdfa_part,
        pdfa_conformance=pdfa_conformance,
        has_xml_attachment=has_xml,
        is_zugferd=is_zugferd,
        attachments=checked,
    )
