from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.errors import ServiceError
from app.models import XmlClassification
from app.pdf_extractor import ExtractedAttachment, extract_attachments, looks_like_xml
from app.xml_identifier import identify_xml


@dataclass(frozen=True, slots=True)
class PdfExtractionResult:
    xml_attachment: ExtractedAttachment
    xml_classification: XmlClassification
    other_attachments: list[ExtractedAttachment]


def process_pdf(pdf_bytes: bytes, settings: Settings) -> PdfExtractionResult:
    attachments = extract_attachments(
        pdf_bytes, max_total_bytes=settings.max_attachment_total_bytes
    )
    xml_attachments = [attachment for attachment in attachments if looks_like_xml(attachment)]

    if not xml_attachments:
        raise ServiceError("xml_attachment_not_found", "PDF contains no XML attachment")
    if len(xml_attachments) > 1:
        raise ServiceError(
            "ambiguous_xml_attachments",
            "PDF contains more than one XML attachment",
            details={"count": len(xml_attachments)},
        )

    xml_attachment = xml_attachments[0]
    if len(xml_attachment.content) > settings.max_xml_bytes:
        raise ServiceError(
            "payload_too_large",
            "Extracted XML exceeds the configured XML size limit",
            status_code=413,
            details={"max_bytes": settings.max_xml_bytes},
        )
    classification = identify_xml(xml_attachment.content)
    others = [attachment for attachment in attachments if attachment is not xml_attachment]
    return PdfExtractionResult(xml_attachment, classification, others)
