from __future__ import annotations

import pytest

from app.errors import ServiceError
from app.models import InvoiceStandard, XmlSyntax
from app.xml_identifier import identify_xml


def test_identifies_factur_x_cii(cii_xml: bytes) -> None:
    result = identify_xml(cii_xml)
    assert result.syntax is XmlSyntax.CII
    assert result.standard is InvoiceStandard.ZUGFERD_FACTUR_X
    assert result.profile == "EN16931"
    assert result.version == "1.0"


def test_identifies_xrechnung_ubl(ubl_xml: bytes) -> None:
    result = identify_xml(ubl_xml)
    assert result.syntax is XmlSyntax.UBL
    assert result.standard is InvoiceStandard.XRECHNUNG
    assert result.profile == "XRECHNUNG"
    assert result.version == "3.0"


def test_identifies_xrechnung_cii() -> None:
    xml = b"""<rsm:CrossIndustryInvoice
      xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
      xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">
      <rsm:ExchangedDocumentContext>
        <ram:GuidelineSpecifiedDocumentContextParameter>
          <ram:ID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</ram:ID>
        </ram:GuidelineSpecifiedDocumentContextParameter>
      </rsm:ExchangedDocumentContext>
    </rsm:CrossIndustryInvoice>"""
    result = identify_xml(xml)
    assert result.syntax is XmlSyntax.CII
    assert result.standard is InvoiceStandard.XRECHNUNG
    assert result.profile == "XRECHNUNG"
    assert result.version == "3.0"


def test_identifies_legacy_zugferd_identifier() -> None:
    xml = b"""<rsm:CrossIndustryInvoice
      xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
      xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">
      <rsm:ExchangedDocumentContext>
        <ram:GuidelineSpecifiedDocumentContextParameter>
          <ram:ID>urn:zugferd.de:2p0:basic</ram:ID>
        </ram:GuidelineSpecifiedDocumentContextParameter>
      </rsm:ExchangedDocumentContext>
    </rsm:CrossIndustryInvoice>"""
    result = identify_xml(xml)
    assert result.standard is InvoiceStandard.ZUGFERD_FACTUR_X
    assert result.profile == "BASIC"
    assert result.version == "2.0"


def test_identifies_ubl_credit_note_with_arbitrary_prefix() -> None:
    xml = b"""\xef\xbb\xbf<doc:CreditNote
      xmlns:doc="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
      xmlns:x="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
      <x:CustomizationID>urn:cen.eu:en16931:2017</x:CustomizationID>
    </doc:CreditNote>"""
    result = identify_xml(xml)
    assert result.syntax is XmlSyntax.UBL
    assert result.document_type == "CreditNote"
    assert result.standard is InvoiceStandard.EN16931


@pytest.mark.parametrize(
    "root_name",
    ["Invoice", "CreditNote", "DebitNote", "SelfBilledInvoice", "SelfBilledCreditNote"],
)
def test_identifies_ubl_invoice_family_document_roots(root_name: str) -> None:
    xml = (
        f'<doc:{root_name} xmlns:doc="urn:oasis:names:specification:ubl:schema:xsd:{root_name}-2" />'
    ).encode()
    result = identify_xml(xml)
    assert result.syntax is XmlSyntax.UBL
    assert result.document_type == root_name


def test_unknown_well_formed_xml_returns_unknown() -> None:
    result = identify_xml(b"  <root><value>1</value></root>")
    assert result.syntax is XmlSyntax.UNKNOWN
    assert result.standard is InvoiceStandard.UNKNOWN


def test_malformed_xml_is_rejected() -> None:
    with pytest.raises(ServiceError, match="not well formed") as error:
        identify_xml(b"<Invoice>")
    assert error.value.code == "malformed_xml"


def test_external_entity_is_rejected() -> None:
    xml = b'<!DOCTYPE root [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root>&xxe;</root>'
    with pytest.raises(ServiceError) as error:
        identify_xml(xml)
    assert error.value.code == "unsafe_xml"
