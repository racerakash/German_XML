from __future__ import annotations

import base64
import binascii
import hashlib
import html
import threading
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Iterable
from xml.etree.ElementTree import Element

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.errors import ServiceError
from app.invoice_types import invoice_title
from app.models import XmlClassification, XmlSyntax
from app.xml_identifier import _expanded_name, identify_xml_root, parse_xml_root

ScalarKey = tuple[int, str]

NAVY = colors.HexColor("#17324D")
BLUE = colors.HexColor("#2176AE")
PALE_BLUE = colors.HexColor("#EAF3F8")
SLATE = colors.HexColor("#536475")
LIGHT_GREY = colors.HexColor("#E5EAF0")
VERY_LIGHT_GREY = colors.HexColor("#F6F8FA")
WHITE = colors.white

_FONT_LOCK = threading.Lock()
_FONTS_REGISTERED = False


@dataclass(frozen=True, slots=True)
class DisplayField:
    label: str
    value: str


@dataclass(slots=True)
class PartyView:
    heading: str
    fields: list[DisplayField] = field(default_factory=list)


@dataclass(slots=True)
class LineView:
    line_id: str = ""
    description: str = ""
    quantity: str = ""
    unit_price: str = ""
    tax: str = ""
    net_amount: str = ""


@dataclass(slots=True)
class InvoiceView:
    title: str
    document_id: str
    metadata: list[DisplayField] = field(default_factory=list)
    references: list[DisplayField] = field(default_factory=list)
    seller: PartyView = field(default_factory=lambda: PartyView("Seller"))
    buyer: PartyView = field(default_factory=lambda: PartyView("Buyer"))
    delivery: list[DisplayField] = field(default_factory=list)
    payment: list[DisplayField] = field(default_factory=list)
    adjustments: list[DisplayField] = field(default_factory=list)
    taxes: list[DisplayField] = field(default_factory=list)
    totals: list[DisplayField] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    lines: list[LineView] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ScalarField:
    path: str
    value: str


def _local_name(element: Element) -> str:
    return _expanded_name(str(element.tag)).local_name


def _children(element: Element, name: str) -> list[Element]:
    return [child for child in list(element) if _local_name(child) == name]


def _first_path(element: Element | None, *names: str) -> Element | None:
    current = element
    for name in names:
        if current is None:
            return None
        matches = _children(current, name)
        if not matches:
            return None
        current = matches[0]
    return current


def _all_path(element: Element | None, *names: str) -> list[Element]:
    if element is None or not names:
        return []
    current = [element]
    for name in names:
        next_level: list[Element] = []
        for parent in current:
            next_level.extend(_children(parent, name))
        current = next_level
    return current


class XmlAccessor:
    def __init__(self) -> None:
        self.consumed: set[ScalarKey] = set()

    def text(self, element: Element | None) -> str | None:
        if element is None or element.text is None:
            return None
        value = element.text.strip()
        if not value:
            return None
        self.consumed.add((id(element), "#text"))
        return value

    def attribute(self, element: Element | None, name: str) -> str | None:
        if element is None or name not in element.attrib:
            return None
        self.consumed.add((id(element), f"@{name}"))
        return element.attrib[name]

    def value(self, element: Element | None, *path: str) -> str | None:
        return self.text(_first_path(element, *path))

    def first_value(self, element: Element | None, paths: Iterable[tuple[str, ...]]) -> str | None:
        for path in paths:
            candidate = self.value(element, *path)
            if candidate is not None:
                return candidate
        return None

    def money(self, element: Element | None) -> str | None:
        value = self.text(element)
        if value is None:
            return None
        currency = self.attribute(element, "currencyID")
        return f"{value} {currency}" if currency else value

    def quantity(self, element: Element | None) -> str | None:
        value = self.text(element)
        if value is None:
            return None
        unit = self.attribute(element, "unitCode")
        return f"{value} {unit}" if unit else value

    def date(self, element: Element | None) -> str | None:
        value = self.text(element)
        if value is None:
            return None
        date_format = self.attribute(element, "format")
        return f"{value} (format {date_format})" if date_format else value


def _add(target: list[DisplayField], label: str, value: str | None) -> None:
    if value is not None and value != "":
        target.append(DisplayField(label, value))


def _join_values(values: Iterable[str | None], separator: str = " / ") -> str | None:
    present = [value for value in values if value]
    return separator.join(present) if present else None


def _extract_ubl_party(container: Element | None, heading: str, access: XmlAccessor) -> PartyView:
    party = _first_path(container, "Party")
    view = PartyView(heading)
    name = access.first_value(
        party,
        (
            ("PartyName", "Name"),
            ("PartyLegalEntity", "RegistrationName"),
            ("Name",),
        ),
    )
    _add(view.fields, "Name", name)
    legal_id_element = _first_path(party, "PartyLegalEntity", "CompanyID")
    legal_id = access.text(legal_id_element)
    scheme = access.attribute(legal_id_element, "schemeID")
    _add(view.fields, "Registration ID", _join_values((legal_id, scheme and f"scheme {scheme}")))
    endpoint = _first_path(party, "EndpointID")
    endpoint_value = access.text(endpoint)
    endpoint_scheme = access.attribute(endpoint, "schemeID")
    _add(view.fields, "Electronic address", _join_values((endpoint_value, endpoint_scheme and f"scheme {endpoint_scheme}")))

    tax_ids: list[str] = []
    for tax_scheme in _all_path(party, "PartyTaxScheme"):
        company_id = access.value(tax_scheme, "CompanyID")
        tax_scheme_id = access.value(tax_scheme, "TaxScheme", "ID")
        combined = _join_values((company_id, tax_scheme_id and f"({tax_scheme_id})"), " ")
        if combined:
            tax_ids.append(combined)
    _add(view.fields, "Tax registration", "; ".join(tax_ids) if tax_ids else None)

    address = _first_path(party, "PostalAddress")
    street = _join_values(
        (
            access.value(address, "StreetName"),
            access.value(address, "AdditionalStreetName"),
        ),
        ", ",
    )
    city = _join_values(
        (
            access.value(address, "PostalZone"),
            access.value(address, "CityName"),
        ),
        " ",
    )
    country = _join_values(
        (
            access.value(address, "CountrySubentity"),
            access.value(address, "Country", "IdentificationCode"),
        ),
        ", ",
    )
    _add(view.fields, "Address", _join_values((street, city, country), "\n"))

    contact = _first_path(party, "Contact")
    _add(view.fields, "Contact", access.value(contact, "Name"))
    _add(view.fields, "Telephone", access.value(contact, "Telephone"))
    _add(view.fields, "Email", access.value(contact, "ElectronicMail"))
    return view


def _extract_cii_party(party: Element | None, heading: str, access: XmlAccessor) -> PartyView:
    view = PartyView(heading)
    _add(view.fields, "Name", access.value(party, "Name"))
    legal_id_element = _first_path(party, "SpecifiedLegalOrganization", "ID")
    legal_id = access.text(legal_id_element)
    scheme = access.attribute(legal_id_element, "schemeID")
    _add(view.fields, "Registration ID", _join_values((legal_id, scheme and f"scheme {scheme}")))

    tax_ids: list[str] = []
    for registration in _all_path(party, "SpecifiedTaxRegistration"):
        identifier = _first_path(registration, "ID")
        value = access.text(identifier)
        scheme_value = access.attribute(identifier, "schemeID")
        combined = _join_values((value, scheme_value and f"({scheme_value})"), " ")
        if combined:
            tax_ids.append(combined)
    _add(view.fields, "Tax registration", "; ".join(tax_ids) if tax_ids else None)

    uri = _first_path(party, "URIUniversalCommunication", "URIID")
    uri_value = access.text(uri)
    uri_scheme = access.attribute(uri, "schemeID")
    _add(view.fields, "Electronic address", _join_values((uri_value, uri_scheme and f"scheme {uri_scheme}")))

    address = _first_path(party, "PostalTradeAddress")
    street = _join_values(
        (
            access.value(address, "LineOne"),
            access.value(address, "LineTwo"),
            access.value(address, "LineThree"),
        ),
        ", ",
    )
    city = _join_values(
        (
            access.value(address, "PostcodeCode"),
            access.value(address, "CityName"),
        ),
        " ",
    )
    country = _join_values(
        (
            access.value(address, "CountrySubDivisionName"),
            access.value(address, "CountryID"),
        ),
        ", ",
    )
    _add(view.fields, "Address", _join_values((street, city, country), "\n"))

    contact = _first_path(party, "DefinedTradeContact")
    _add(
        view.fields,
        "Contact",
        _join_values(
            (
                access.value(contact, "PersonName"),
                access.value(contact, "DepartmentName"),
            ),
            ", ",
        ),
    )
    _add(
        view.fields,
        "Telephone",
        access.value(contact, "TelephoneUniversalCommunication", "CompleteNumber"),
    )
    _add(
        view.fields,
        "Email",
        access.value(contact, "EmailURIUniversalCommunication", "URIID"),
    )
    return view


def _extract_ubl_line(line: Element, access: XmlAccessor) -> LineView:
    quantity_element = None
    for quantity_name in ("InvoicedQuantity", "CreditedQuantity", "DebitedQuantity"):
        quantity_element = _first_path(line, quantity_name)
        if quantity_element is not None:
            break
    price_element = _first_path(line, "Price", "PriceAmount")
    amount_element = _first_path(line, "LineExtensionAmount")
    item = _first_path(line, "Item")
    description = _join_values(
        (
            access.value(item, "Name"),
            access.value(item, "Description"),
            access.value(item, "SellersItemIdentification", "ID"),
            access.value(item, "BuyersItemIdentification", "ID"),
        ),
        " - ",
    )
    tax_category = _first_path(item, "ClassifiedTaxCategory")
    tax = _join_values(
        (
            access.value(tax_category, "ID"),
            access.value(tax_category, "Percent") and f"{access.value(tax_category, 'Percent')}%",
        )
    )
    return LineView(
        line_id=access.value(line, "ID") or "",
        description=description or "",
        quantity=access.quantity(quantity_element) or "",
        unit_price=access.money(price_element) or "",
        tax=tax or "",
        net_amount=access.money(amount_element) or "",
    )


def _extract_cii_line(line: Element, access: XmlAccessor) -> LineView:
    product = _first_path(line, "SpecifiedTradeProduct")
    description = _join_values(
        (
            access.value(product, "Name"),
            access.value(product, "Description"),
            access.value(product, "SellerAssignedID"),
            access.value(product, "BuyerAssignedID"),
        ),
        " - ",
    )
    settlement = _first_path(line, "SpecifiedLineTradeSettlement")
    tax_element = _first_path(settlement, "ApplicableTradeTax")
    tax_rate = access.value(tax_element, "RateApplicablePercent")
    tax = _join_values(
        (
            access.value(tax_element, "CategoryCode"),
            tax_rate and f"{tax_rate}%",
        )
    )
    return LineView(
        line_id=access.value(line, "AssociatedDocumentLineDocument", "LineID") or "",
        description=description or "",
        quantity=access.quantity(_first_path(line, "SpecifiedLineTradeDelivery", "BilledQuantity")) or "",
        unit_price=access.money(
            _first_path(line, "SpecifiedLineTradeAgreement", "NetPriceProductTradePrice", "ChargeAmount")
        )
        or "",
        tax=tax or "",
        net_amount=access.money(
            _first_path(settlement, "SpecifiedTradeSettlementLineMonetarySummation", "LineTotalAmount")
        )
        or "",
    )


def _extract_ubl_view(root: Element, access: XmlAccessor) -> InvoiceView:
    root_name = _local_name(root)
    type_elements = {
        "Invoice": "InvoiceTypeCode",
        "SelfBilledInvoice": "InvoiceTypeCode",
        "CreditNote": "CreditNoteTypeCode",
        "SelfBilledCreditNote": "CreditNoteTypeCode",
        "DebitNote": "DebitNoteTypeCode",
    }
    line_elements = {
        "Invoice": "InvoiceLine",
        "SelfBilledInvoice": "InvoiceLine",
        "CreditNote": "CreditNoteLine",
        "SelfBilledCreditNote": "CreditNoteLine",
        "DebitNote": "DebitNoteLine",
    }
    type_element = type_elements[root_name]
    type_code = access.value(root, type_element)
    title = invoice_title(type_code, root_name)
    document_id = access.value(root, "ID") or ""
    view = InvoiceView(title=title, document_id=document_id)
    _add(view.metadata, "Document number", document_id)
    _add(view.metadata, "Issue date", access.value(root, "IssueDate"))
    _add(view.metadata, "Due date", access.value(root, "DueDate"))
    _add(view.metadata, "Document type", type_code)
    _add(view.metadata, "Document currency", access.value(root, "DocumentCurrencyCode"))
    _add(view.metadata, "Tax currency", access.value(root, "TaxCurrencyCode"))
    _add(view.references, "Buyer reference", access.value(root, "BuyerReference"))
    _add(view.references, "Order reference", access.value(root, "OrderReference", "ID"))
    _add(view.references, "Contract reference", access.value(root, "ContractDocumentReference", "ID"))
    for index, reference in enumerate(_all_path(root, "AdditionalDocumentReference"), start=1):
        value = _join_values(
            (
                access.value(reference, "ID"),
                access.value(reference, "DocumentDescription"),
            ),
            " - ",
        )
        _add(view.references, f"Additional document {index}", value)

    view.seller = _extract_ubl_party(_first_path(root, "AccountingSupplierParty"), "Seller", access)
    view.buyer = _extract_ubl_party(_first_path(root, "AccountingCustomerParty"), "Buyer", access)

    delivery = _first_path(root, "Delivery")
    _add(view.delivery, "Actual delivery date", access.value(delivery, "ActualDeliveryDate"))
    _add(view.delivery, "Delivery location", access.value(delivery, "DeliveryLocation", "ID"))
    delivery_address = _first_path(delivery, "DeliveryLocation", "Address")
    _add(
        view.delivery,
        "Delivery address",
        _join_values(
            (
                access.value(delivery_address, "StreetName"),
                _join_values(
                    (
                        access.value(delivery_address, "PostalZone"),
                        access.value(delivery_address, "CityName"),
                    ),
                    " ",
                ),
                access.value(delivery_address, "Country", "IdentificationCode"),
            ),
            ", ",
        ),
    )

    for index, means in enumerate(_all_path(root, "PaymentMeans"), start=1):
        prefix = f"Payment {index}"
        _add(view.payment, f"{prefix} means", access.value(means, "PaymentMeansCode"))
        _add(view.payment, f"{prefix} reference", access.value(means, "PaymentID"))
        _add(view.payment, f"{prefix} account", access.value(means, "PayeeFinancialAccount", "ID"))
        _add(view.payment, f"{prefix} account name", access.value(means, "PayeeFinancialAccount", "Name"))
        _add(
            view.payment,
            f"{prefix} institution",
            access.value(means, "PayeeFinancialAccount", "FinancialInstitutionBranch", "ID"),
        )
    for index, terms in enumerate(_all_path(root, "PaymentTerms"), start=1):
        _add(view.payment, f"Payment terms {index}", access.value(terms, "Note"))
        _add(view.payment, f"Payment due date {index}", access.value(terms, "PaymentDueDate"))

    line_name = line_elements[root_name]
    view.lines = [_extract_ubl_line(line, access) for line in _all_path(root, line_name)]

    for index, adjustment in enumerate(_all_path(root, "AllowanceCharge"), start=1):
        indicator = access.value(adjustment, "ChargeIndicator")
        kind = "Charge" if indicator and indicator.lower() == "true" else "Allowance"
        value = _join_values(
            (
                access.value(adjustment, "AllowanceChargeReason"),
                access.money(_first_path(adjustment, "Amount")),
            ),
            ": ",
        )
        _add(view.adjustments, f"{kind} {index}", value)

    for index, total in enumerate(_all_path(root, "TaxTotal"), start=1):
        _add(view.taxes, f"Tax total {index}", access.money(_first_path(total, "TaxAmount")))
        for subindex, subtotal in enumerate(_all_path(total, "TaxSubtotal"), start=1):
            detail = _join_values(
                (
                    access.money(_first_path(subtotal, "TaxableAmount")),
                    access.money(_first_path(subtotal, "TaxAmount")),
                    access.value(subtotal, "TaxCategory", "ID"),
                    access.value(subtotal, "TaxCategory", "Percent")
                    and f"{access.value(subtotal, 'TaxCategory', 'Percent')}%",
                )
            )
            _add(view.taxes, f"Tax subtotal {index}.{subindex}", detail)

    totals = _first_path(root, "LegalMonetaryTotal")
    if totals is None:
        totals = _first_path(root, "RequestedMonetaryTotal")
    for label, name in (
        ("Line net total", "LineExtensionAmount"),
        ("Tax exclusive total", "TaxExclusiveAmount"),
        ("Tax inclusive total", "TaxInclusiveAmount"),
        ("Allowance total", "AllowanceTotalAmount"),
        ("Charge total", "ChargeTotalAmount"),
        ("Prepaid amount", "PrepaidAmount"),
        ("Payable amount", "PayableAmount"),
    ):
        _add(view.totals, label, access.money(_first_path(totals, name)))

    for note in _all_path(root, "Note"):
        value = access.text(note)
        if value:
            view.notes.append(value)
    return view


def _extract_cii_view(root: Element, access: XmlAccessor) -> InvoiceView:
    document = _first_path(root, "ExchangedDocument")
    transaction = _first_path(root, "SupplyChainTradeTransaction")
    agreement = _first_path(transaction, "ApplicableHeaderTradeAgreement")
    delivery = _first_path(transaction, "ApplicableHeaderTradeDelivery")
    settlement = _first_path(transaction, "ApplicableHeaderTradeSettlement")
    document_id = access.value(document, "ID") or ""
    document_type_code = access.value(document, "TypeCode")
    view = InvoiceView(
        title=invoice_title(document_type_code, _local_name(root)),
        document_id=document_id,
    )
    _add(view.metadata, "Document number", document_id)
    _add(view.metadata, "Document type", document_type_code)
    _add(
        view.metadata,
        "Issue date",
        access.date(_first_path(document, "IssueDateTime", "DateTimeString")),
    )
    _add(view.metadata, "Document currency", access.value(settlement, "InvoiceCurrencyCode"))

    view.seller = _extract_cii_party(_first_path(agreement, "SellerTradeParty"), "Seller", access)
    view.buyer = _extract_cii_party(_first_path(agreement, "BuyerTradeParty"), "Buyer", access)
    _add(view.references, "Buyer reference", access.value(agreement, "BuyerReference"))
    for label, path in (
        ("Seller order reference", ("SellerOrderReferencedDocument", "IssuerAssignedID")),
        ("Buyer order reference", ("BuyerOrderReferencedDocument", "IssuerAssignedID")),
        ("Contract reference", ("ContractReferencedDocument", "IssuerAssignedID")),
    ):
        _add(view.references, label, access.value(agreement, *path))

    _add(
        view.delivery,
        "Actual delivery date",
        access.date(
            _first_path(
                delivery,
                "ActualDeliverySupplyChainEvent",
                "OccurrenceDateTime",
                "DateTimeString",
            )
        ),
    )
    _add(view.payment, "Payment reference", access.value(settlement, "PaymentReference"))
    for index, terms in enumerate(_all_path(settlement, "SpecifiedTradePaymentTerms"), start=1):
        _add(view.payment, f"Payment terms {index}", access.value(terms, "Description"))
        _add(
            view.payment,
            f"Payment due date {index}",
            access.date(_first_path(terms, "DueDateDateTime", "DateTimeString")),
        )
    for index, means in enumerate(_all_path(settlement, "SpecifiedTradeSettlementPaymentMeans"), start=1):
        prefix = f"Payment {index}"
        _add(view.payment, f"{prefix} means", access.value(means, "TypeCode"))
        _add(view.payment, f"{prefix} information", access.value(means, "Information"))
        _add(
            view.payment,
            f"{prefix} account",
            access.first_value(
                means,
                (
                    ("PayeePartyCreditorFinancialAccount", "IBANID"),
                    ("PayeePartyCreditorFinancialAccount", "ProprietaryID"),
                ),
            ),
        )
        _add(
            view.payment,
            f"{prefix} institution",
            access.first_value(
                means,
                (
                    ("PayeeSpecifiedCreditorFinancialInstitution", "BICID"),
                    ("PayeeSpecifiedCreditorFinancialInstitution", "Name"),
                ),
            ),
        )

    view.lines = [
        _extract_cii_line(line, access)
        for line in _all_path(transaction, "IncludedSupplyChainTradeLineItem")
    ]

    for index, adjustment in enumerate(_all_path(settlement, "SpecifiedTradeAllowanceCharge"), start=1):
        indicator = access.value(adjustment, "ChargeIndicator")
        kind = "Charge" if indicator and indicator.lower() == "true" else "Allowance"
        value = _join_values(
            (
                access.value(adjustment, "Reason"),
                access.money(_first_path(adjustment, "ActualAmount")),
            ),
            ": ",
        )
        _add(view.adjustments, f"{kind} {index}", value)

    for index, tax in enumerate(_all_path(settlement, "ApplicableTradeTax"), start=1):
        rate = access.value(tax, "RateApplicablePercent")
        detail = _join_values(
            (
                access.money(_first_path(tax, "BasisAmount")),
                access.money(_first_path(tax, "CalculatedAmount")),
                access.value(tax, "CategoryCode"),
                rate and f"{rate}%",
                access.value(tax, "ExemptionReason"),
            )
        )
        _add(view.taxes, f"Tax {index}", detail)

    totals = _first_path(settlement, "SpecifiedTradeSettlementHeaderMonetarySummation")
    for label, name in (
        ("Line net total", "LineTotalAmount"),
        ("Charge total", "ChargeTotalAmount"),
        ("Allowance total", "AllowanceTotalAmount"),
        ("Tax basis total", "TaxBasisTotalAmount"),
        ("Tax total", "TaxTotalAmount"),
        ("Grand total", "GrandTotalAmount"),
        ("Prepaid amount", "TotalPrepaidAmount"),
        ("Payable amount", "DuePayableAmount"),
    ):
        _add(view.totals, label, access.money(_first_path(totals, name)))

    for note in _all_path(document, "IncludedNote"):
        value = access.value(note, "Content")
        if value:
            view.notes.append(value)
    return view


def _binary_metadata(element: Element) -> str:
    raw = (element.text or "").strip()
    compact = "".join(raw.split())
    try:
        decoded = base64.b64decode(compact, validate=True)
        digest = hashlib.sha256(decoded).hexdigest()
        size = f"{len(decoded)} bytes"
        status = "decoded"
    except (binascii.Error, ValueError):
        encoded = raw.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        size = "unavailable"
        status = "invalid base64; hash covers encoded text"
    attributes = "; ".join(
        f"{name}={value}" for name, value in sorted(element.attrib.items())
    )
    details = ["Binary object", f"decoded size={size}", f"sha256={digest}", status]
    if attributes:
        details.append(attributes)
    return "; ".join(details)


def collect_unconsumed_fields(root: Element, consumed: set[ScalarKey]) -> list[ScalarField]:
    fields: list[ScalarField] = []

    def walk(element: Element, path: str) -> None:
        local_name = _local_name(element)
        is_binary = local_name.endswith("BinaryObject")
        if is_binary:
            keys = {(id(element), "#text")}
            keys.update((id(element), f"@{name}") for name in element.attrib)
            if not keys.issubset(consumed):
                fields.append(ScalarField(path, _binary_metadata(element)))
        else:
            for attribute_name, attribute_value in sorted(element.attrib.items()):
                if (id(element), f"@{attribute_name}") not in consumed:
                    fields.append(ScalarField(f"{path}/@{attribute_name}", attribute_value))
            text_value = (element.text or "").strip()
            if text_value and (id(element), "#text") not in consumed:
                fields.append(ScalarField(path, text_value))

        child_counts: dict[str, int] = {}
        for child in list(element):
            child_name = _local_name(child)
            child_counts[child_name] = child_counts.get(child_name, 0) + 1
            child_path = f"{path}/{child_name}[{child_counts[child_name]}]"
            walk(child, child_path)
            tail_value = (child.tail or "").strip()
            if tail_value and (id(child), "#tail") not in consumed:
                fields.append(ScalarField(f"{child_path}/tail()", tail_value))

    walk(root, f"/{_local_name(root)}[1]")
    return fields


def normalize_invoice(root: Element, classification: XmlClassification) -> tuple[InvoiceView, list[ScalarField]]:
    access = XmlAccessor()
    if classification.syntax is XmlSyntax.UBL:
        view = _extract_ubl_view(root, access)
    elif classification.syntax is XmlSyntax.CII:
        view = _extract_cii_view(root, access)
    else:
        raise ServiceError(
            "unsupported_xml_syntax",
            "PDF rendering supports CII and UBL invoice-family XML documents",
        )
    return view, collect_unconsumed_fields(root, access.consumed)


def _register_fonts() -> None:
    global _FONTS_REGISTERED
    with _FONT_LOCK:
        if _FONTS_REGISTERED:
            return
        font_dir = Path(__file__).parent / "assets" / "fonts"
        regular = font_dir / "NotoSans-Regular.ttf"
        bold = font_dir / "NotoSans-Bold.ttf"
        if not regular.is_file() or not bold.is_file():
            raise RuntimeError("Bundled Noto Sans font files are missing")
        pdfmetrics.registerFont(TTFont("NotoSans", str(regular)))
        pdfmetrics.registerFont(TTFont("NotoSans-Bold", str(bold)))
        pdfmetrics.registerFontFamily(
            "NotoSans",
            normal="NotoSans",
            bold="NotoSans-Bold",
            italic="NotoSans",
            boldItalic="NotoSans-Bold",
        )
        _FONTS_REGISTERED = True


def _safe_markup(value: str) -> str:
    return html.escape(value).replace("\n", "<br/>")


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "InvoiceTitle",
            parent=sample["Title"],
            fontName="NotoSans-Bold",
            fontSize=24,
            leading=29,
            textColor=NAVY,
            spaceAfter=3 * mm,
        ),
        "subtitle": ParagraphStyle(
            "InvoiceSubtitle",
            parent=sample["Normal"],
            fontName="NotoSans",
            fontSize=8.5,
            leading=11,
            textColor=SLATE,
        ),
        "section": ParagraphStyle(
            "SectionHeading",
            parent=sample["Heading2"],
            fontName="NotoSans-Bold",
            fontSize=11,
            leading=14,
            textColor=NAVY,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "InvoiceBody",
            parent=sample["BodyText"],
            fontName="NotoSans",
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#1F2933"),
            wordWrap="CJK",
        ),
        "body_bold": ParagraphStyle(
            "InvoiceBodyBold",
            parent=sample["BodyText"],
            fontName="NotoSans-Bold",
            fontSize=8.5,
            leading=11.5,
            textColor=NAVY,
            wordWrap="CJK",
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=sample["BodyText"],
            fontName="NotoSans-Bold",
            fontSize=8,
            leading=10.5,
            textColor=WHITE,
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "SmallBody",
            parent=sample["BodyText"],
            fontName="NotoSans",
            fontSize=7.2,
            leading=9.5,
            textColor=SLATE,
            wordWrap="CJK",
        ),
        "appendix_path": ParagraphStyle(
            "AppendixPath",
            parent=sample["BodyText"],
            fontName="NotoSans-Bold",
            fontSize=7,
            leading=9,
            textColor=BLUE,
            wordWrap="CJK",
            spaceBefore=1.5 * mm,
        ),
        "appendix_value": ParagraphStyle(
            "AppendixValue",
            parent=sample["BodyText"],
            fontName="NotoSans",
            fontSize=7.3,
            leading=9.5,
            textColor=colors.HexColor("#263746"),
            wordWrap="CJK",
            leftIndent=3 * mm,
            borderColor=LIGHT_GREY,
            borderWidth=0.5,
            borderPadding=2 * mm,
            backColor=VERY_LIGHT_GREY,
        ),
    }


def _paragraph(value: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_safe_markup(value), style)


def _section_table(fields: list[DisplayField], styles: dict[str, ParagraphStyle], width: float) -> Table:
    rows = [
        [_paragraph(item.label, styles["body_bold"]), _paragraph(item.value, styles["body"])]
        for item in fields
    ]
    table = Table(rows, colWidths=[42 * mm, width - 42 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.5, LIGHT_GREY),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, LIGHT_GREY),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4 * mm),
            ]
        )
    )
    return table


def _party_card(party: PartyView, styles: dict[str, ParagraphStyle], width: float) -> Table:
    content: list[object] = [_paragraph(party.heading, styles["body_bold"]), Spacer(1, 1.5 * mm)]
    if party.fields:
        for item in party.fields:
            content.append(_paragraph(item.label, styles["small"]))
            content.append(_paragraph(item.value, styles["body"]))
            content.append(Spacer(1, 1 * mm))
    else:
        content.append(_paragraph("No party information supplied", styles["small"]))
    table = Table([[content]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), VERY_LIGHT_GREY),
                ("BOX", (0, 0), (-1, -1), 0.6, LIGHT_GREY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    return table


def _line_table(lines: list[LineView], styles: dict[str, ParagraphStyle], width: float) -> LongTable:
    headers = ["Line", "Description", "Quantity", "Unit price", "Tax", "Net amount"]
    rows: list[list[Paragraph]] = [[_paragraph(item, styles["table_header"]) for item in headers]]
    for line in lines:
        rows.append(
            [
                _paragraph(line.line_id, styles["body"]),
                _paragraph(line.description, styles["body"]),
                _paragraph(line.quantity, styles["body"]),
                _paragraph(line.unit_price, styles["body"]),
                _paragraph(line.tax, styles["body"]),
                _paragraph(line.net_amount, styles["body"]),
            ]
        )
    proportions = [0.08, 0.36, 0.14, 0.15, 0.11, 0.16]
    table = LongTable(
        rows,
        colWidths=[width * value for value in proportions],
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, VERY_LIGHT_GREY]),
                ("BOX", (0, 0), (-1, -1), 0.5, LIGHT_GREY),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, LIGHT_GREY),
                ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
            ]
        )
    )
    return table


def _page_decorator(title: str, document_id: str):
    def decorate(canvas, doc) -> None:
        canvas.saveState()
        canvas.setTitle(f"{title} {document_id}".strip())
        canvas.setAuthor("German E-Invoice Extractor")
        canvas.setSubject("Informational visualization; source XML remains authoritative")
        canvas.setFont("NotoSans-Bold", 8)
        canvas.setFillColor(NAVY)
        canvas.drawString(20 * mm, A4[1] - 13 * mm, title)
        canvas.setFont("NotoSans", 7.5)
        canvas.setFillColor(SLATE)
        if document_id:
            canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 13 * mm, document_id)
        canvas.setStrokeColor(LIGHT_GREY)
        canvas.line(20 * mm, A4[1] - 16 * mm, A4[0] - 20 * mm, A4[1] - 16 * mm)
        canvas.setFont("NotoSans", 7)
        canvas.drawString(20 * mm, 10 * mm, "Informational visualization - source XML remains authoritative")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    return decorate


def render_invoice_pdf(xml_bytes: bytes) -> tuple[bytes, XmlClassification]:
    root = parse_xml_root(xml_bytes)
    classification = identify_xml_root(root)
    view, appendix_fields = normalize_invoice(root, classification)
    _register_fonts()
    styles = _styles()

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=17 * mm,
        title=f"{view.title} {view.document_id}".strip(),
        author="German E-Invoice Extractor",
    )
    width = A4[0] - document.leftMargin - document.rightMargin
    story: list[object] = []
    story.append(_paragraph(view.title, styles["title"]))
    classification_text = " | ".join(
        value
        for value in (
            classification.syntax.value,
            classification.standard.value,
            classification.profile,
            classification.version and f"version {classification.version}",
        )
        if value
    )
    story.append(_paragraph(classification_text, styles["subtitle"]))
    story.append(Spacer(1, 4 * mm))

    if view.metadata:
        story.append(_paragraph("Document details", styles["section"]))
        story.append(_section_table(view.metadata, styles, width))

    story.append(_paragraph("Parties", styles["section"]))
    party_gap = 4 * mm
    party_width = (width - party_gap) / 2
    parties = Table(
        [[_party_card(view.seller, styles, party_width), _party_card(view.buyer, styles, party_width)]],
        colWidths=[party_width, party_width],
        hAlign="LEFT",
    )
    parties.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), party_gap / 2),
                ("LEFTPADDING", (1, 0), (1, 0), party_gap / 2),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(parties)

    for heading, fields in (
        ("References", view.references),
        ("Delivery", view.delivery),
        ("Payment", view.payment),
        ("Allowances and charges", view.adjustments),
    ):
        if fields:
            story.append(
                KeepTogether(
                    [
                        _paragraph(heading, styles["section"]),
                        _section_table(fields, styles, width),
                    ]
                )
            )

    if view.lines:
        story.append(_paragraph("Line items", styles["section"]))
        story.append(_line_table(view.lines, styles, width))

    if view.taxes:
        story.append(
            KeepTogether(
                [
                    _paragraph("Taxes", styles["section"]),
                    _section_table(view.taxes, styles, width),
                ]
            )
        )
    if view.totals:
        totals_table = _section_table(view.totals, styles, width * 0.62)
        totals_table.hAlign = "RIGHT"
        story.append(
            KeepTogether([_paragraph("Totals", styles["section"]), totals_table])
        )
    if view.notes:
        story.append(_paragraph("Notes", styles["section"]))
        for note in view.notes:
            story.append(_paragraph(note, styles["body"]))
            story.append(Spacer(1, 1.5 * mm))

    story.append(PageBreak())
    story.append(_paragraph("Complete XML data appendix", styles["title"]))
    story.append(
        _paragraph(
            "The following XML scalar values and attributes were not already represented in the invoice view. "
            "Binary objects are represented by metadata and SHA-256 digest rather than their base64 payload.",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 3 * mm))
    if appendix_fields:
        for field_item in appendix_fields:
            story.append(_paragraph(field_item.path, styles["appendix_path"]))
            story.append(_paragraph(field_item.value, styles["appendix_value"]))
    else:
        story.append(_paragraph("All XML scalar values are represented in the invoice view.", styles["body"]))

    decorator = _page_decorator(view.title, view.document_id)
    try:
        document.build(story, onFirstPage=decorator, onLaterPages=decorator)
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError(
            "pdf_render_failed",
            "The invoice PDF could not be rendered",
            status_code=500,
        ) from exc
    return buffer.getvalue(), classification
