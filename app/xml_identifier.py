from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from app.errors import ServiceError
from app.models import InvoiceStandard, XmlClassification, XmlSyntax

UBL_INVOICE_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
UBL_CREDIT_NOTE_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
CII_NAMESPACE_MARKER = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice"


@dataclass(frozen=True, slots=True)
class ExpandedName:
    namespace: str
    local_name: str


def _expanded_name(tag: str) -> ExpandedName:
    if tag.startswith("{") and "}" in tag:
        namespace, local_name = tag[1:].split("}", 1)
        return ExpandedName(namespace, local_name)
    return ExpandedName("", tag)


def _element_text_by_local_name(root: object, names: set[str]) -> list[str]:
    values: list[str] = []
    for element in root.iter():  # type: ignore[attr-defined]
        expanded = _expanded_name(str(element.tag))
        if expanded.local_name in names and element.text and element.text.strip():
            values.append(element.text.strip())
    return values


def _guideline_candidates(root: object, syntax: XmlSyntax) -> list[str]:
    if syntax is XmlSyntax.UBL:
        direct: list[str] = []
        for child in list(root):  # type: ignore[arg-type]
            if _expanded_name(str(child.tag)).local_name in {
                "CustomizationID",
                "ProfileID",
            } and child.text:
                direct.append(child.text.strip())
        return [value for value in direct if value]

    if syntax is XmlSyntax.CII:
        candidates: list[str] = []
        for element in root.iter():  # type: ignore[attr-defined]
            if _expanded_name(str(element.tag)).local_name != "GuidelineSpecifiedDocumentContextParameter":
                continue
            candidates.extend(_element_text_by_local_name(element, {"ID"}))
        return candidates
    return []


def _extract_version(identifier: str) -> str | None:
    lowered = identifier.lower()
    p_encoded = re.search(r"(?:^|:)(\d+)p(\d+)(?:p(\d+))?(?::|$)", lowered)
    if p_encoded:
        return ".".join(part for part in p_encoded.groups() if part is not None)
    for pattern in (
        r"xrechnung[_:-]?(\d+(?:\.\d+){0,2})",
        r"(?:factur-x|zugferd)[^0-9]*(\d+(?:\.\d+){0,2})",
    ):
        match = re.search(pattern, lowered)
        if match:
            return match.group(1)
    return None


def _extract_profile(identifier: str) -> str | None:
    lowered = identifier.lower()
    known_profiles = (
        ("extended-ctc-fr", "EXTENDED-CTC-FR"),
        ("xrechnung", "XRECHNUNG"),
        ("minimum", "MINIMUM"),
        ("basicwl", "BASIC-WL"),
        ("basic", "BASIC"),
        ("en16931", "EN16931"),
        ("comfort", "COMFORT"),
        ("extended", "EXTENDED"),
    )
    for marker, label in known_profiles:
        if marker in lowered:
            return label
    return None


def _classify_standard(identifiers: list[str]) -> tuple[InvoiceStandard, str | None, str | None, str | None]:
    guideline = identifiers[0] if identifiers else None
    lowered = " ".join(identifiers).lower()

    if "xrechnung" in lowered or "xoeinkauf.de" in lowered:
        selected = next(
            (value for value in identifiers if "xrechnung" in value.lower() or "xoeinkauf.de" in value.lower()),
            guideline,
        )
        return (
            InvoiceStandard.XRECHNUNG,
            _extract_profile(selected or lowered),
            _extract_version(selected or lowered),
            selected,
        )

    if any(marker in lowered for marker in ("factur-x", "facturx", "zugferd")):
        selected = next(
            (
                value
                for value in identifiers
                if any(marker in value.lower() for marker in ("factur-x", "facturx", "zugferd"))
            ),
            guideline,
        )
        return (
            InvoiceStandard.ZUGFERD_FACTUR_X,
            _extract_profile(selected or lowered),
            _extract_version(selected or lowered),
            selected,
        )

    if any(marker in lowered for marker in ("en16931", "cen.eu:en16931")):
        selected = next(
            (value for value in identifiers if "en16931" in value.lower()), guideline
        )
        return (
            InvoiceStandard.EN16931,
            _extract_profile(selected or lowered),
            _extract_version(selected or lowered),
            selected,
        )

    return InvoiceStandard.UNKNOWN, None, None, guideline


def identify_xml(xml_bytes: bytes) -> XmlClassification:
    try:
        root = DefusedET.parse(BytesIO(xml_bytes)).getroot()
    except DefusedXmlException as exc:
        raise ServiceError("unsafe_xml", "XML content uses a prohibited construct") from exc
    except (ParseError, ValueError, TypeError) as exc:
        raise ServiceError("malformed_xml", "XML content is not well formed") from exc
    except Exception as exc:
        # defusedxml raises dedicated exceptions for entities and DTD-based attacks.
        raise ServiceError("unsafe_xml", "XML content uses a prohibited construct") from exc

    expanded = _expanded_name(str(root.tag))
    syntax = XmlSyntax.UNKNOWN
    document_type = expanded.local_name or "UNKNOWN"

    if (
        expanded.local_name == "CrossIndustryInvoice"
        and CII_NAMESPACE_MARKER.lower() in expanded.namespace.lower()
    ):
        syntax = XmlSyntax.CII
    elif (
        expanded.local_name == "Invoice" and expanded.namespace == UBL_INVOICE_NS
    ) or (
        expanded.local_name == "CreditNote"
        and expanded.namespace == UBL_CREDIT_NOTE_NS
    ):
        syntax = XmlSyntax.UBL

    identifiers = _guideline_candidates(root, syntax)
    standard, profile, version, guideline = _classify_standard(identifiers)

    if syntax is XmlSyntax.UNKNOWN:
        standard = InvoiceStandard.UNKNOWN
        profile = None
        version = None
        guideline = None

    return XmlClassification(
        syntax=syntax,
        standard=standard,
        profile=profile,
        version=version,
        document_type=document_type,
        root_element=str(root.tag),
        guideline_identifier=guideline,
    )
