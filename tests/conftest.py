from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, NameObject

from app.api import create_app
from app.config import Settings


@pytest.fixture
def cii_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
 xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
 xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:factur-x.eu:1p0:en16931</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
</rsm:CrossIndustryInvoice>"""


@pytest.fixture
def ubl_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xoeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
</Invoice>"""


@pytest.fixture
def rich_ubl_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xoeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
  <cbc:ID>UBL-2026-0042</cbc:ID>
  <cbc:IssueDate>2026-10-06</cbc:IssueDate>
  <cbc:DueDate>2026-11-05</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:Note>Thank you for your business &amp; continued support.</cbc:Note>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>BUYER-REF-7</cbc:BuyerReference>
  <cbc:AccountingCost>Research &amp; Development / Muenchen</cbc:AccountingCost>
  <cac:OrderReference><cbc:ID>PO-9988</cbc:ID></cac:OrderReference>
  <cac:AdditionalDocumentReference>
    <cbc:ID>supporting-document</cbc:ID>
    <cbc:DocumentDescription>Binary test attachment</cbc:DocumentDescription>
    <cac:Attachment>
      <cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain" filename="hello.txt">aGVsbG8=</cbc:EmbeddedDocumentBinaryObject>
    </cac:Attachment>
  </cac:AdditionalDocumentReference>
  <cac:AccountingSupplierParty><cac:Party>
    <cbc:EndpointID schemeID="EM">billing@seller.example</cbc:EndpointID>
    <cac:PartyName><cbc:Name>Seller GmbH</cbc:Name></cac:PartyName>
    <cac:PostalAddress>
      <cbc:StreetName>Hauptstrasse 1</cbc:StreetName><cbc:CityName>Muenchen</cbc:CityName>
      <cbc:PostalZone>80331</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country>
    </cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Seller GmbH</cbc:RegistrationName><cbc:CompanyID schemeID="0204">HRB-123</cbc:CompanyID></cac:PartyLegalEntity>
    <cac:Contact><cbc:Name>Anna Mueller</cbc:Name><cbc:Telephone>+49-89-1234</cbc:Telephone><cbc:ElectronicMail>anna@seller.example</cbc:ElectronicMail></cac:Contact>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>Buyer AG</cbc:Name></cac:PartyName>
    <cac:PostalAddress><cbc:StreetName>Markt 9</cbc:StreetName><cbc:CityName>Berlin</cbc:CityName><cbc:PostalZone>10115</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyLegalEntity><cbc:RegistrationName>Buyer AG</cbc:RegistrationName><cbc:CompanyID>HRB-999</cbc:CompanyID></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:Delivery><cbc:ActualDeliveryDate>2026-10-05</cbc:ActualDeliveryDate><cac:DeliveryLocation><cbc:ID>WAREHOUSE-2</cbc:ID></cac:DeliveryLocation></cac:Delivery>
  <cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode><cbc:PaymentID>UBL-2026-0042</cbc:PaymentID><cac:PayeeFinancialAccount><cbc:ID>DE02120300000000202051</cbc:ID><cbc:Name>Seller operating account</cbc:Name><cac:FinancialInstitutionBranch><cbc:ID>BYLADEM1001</cbc:ID></cac:FinancialInstitutionBranch></cac:PayeeFinancialAccount></cac:PaymentMeans>
  <cac:PaymentTerms><cbc:Note>Payable within 30 days without deduction.</cbc:Note><cbc:PaymentDueDate>2026-11-05</cbc:PaymentDueDate></cac:PaymentTerms>
  <cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator><cbc:AllowanceChargeReason>Loyalty discount</cbc:AllowanceChargeReason><cbc:Amount currencyID="EUR">10.00</cbc:Amount></cac:AllowanceCharge>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">37.81</cbc:TaxAmount><cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">199.00</cbc:TaxableAmount><cbc:TaxAmount currencyID="EUR">37.81</cbc:TaxAmount><cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">209.00</cbc:LineExtensionAmount><cbc:TaxExclusiveAmount currencyID="EUR">199.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">236.81</cbc:TaxInclusiveAmount><cbc:AllowanceTotalAmount currencyID="EUR">10.00</cbc:AllowanceTotalAmount><cbc:PayableAmount currencyID="EUR">236.81</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="C62">2</cbc:InvoicedQuantity><cbc:LineExtensionAmount currencyID="EUR">200.00</cbc:LineExtensionAmount><cac:Item><cbc:Description>Consulting package with a detailed deliverable description that wraps cleanly across the invoice table.</cbc:Description><cbc:Name>Consulting</cbc:Name><cac:SellersItemIdentification><cbc:ID>CONS-01</cbc:ID></cac:SellersItemIdentification><cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent></cac:ClassifiedTaxCategory></cac:Item><cac:Price><cbc:PriceAmount currencyID="EUR">100.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
  <cac:InvoiceLine><cbc:ID>2</cbc:ID><cbc:InvoicedQuantity unitCode="HUR">1</cbc:InvoicedQuantity><cbc:LineExtensionAmount currencyID="EUR">9.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Support</cbc:Name><cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent></cac:ClassifiedTaxCategory></cac:Item><cac:Price><cbc:PriceAmount currencyID="EUR">9.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</Invoice>"""


@pytest.fixture
def rich_cii_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
 xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">
 <rsm:ExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:factur-x.eu:1p0:en16931</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext>
 <rsm:ExchangedDocument><ram:ID>CII-2026-0007</ram:ID><ram:TypeCode>380</ram:TypeCode><ram:IssueDateTime><ram:DateTimeString format="102">20261006</ram:DateTimeString></ram:IssueDateTime><ram:IncludedNote><ram:Content>Complete CII sample note</ram:Content></ram:IncludedNote></rsm:ExchangedDocument>
 <rsm:SupplyChainTradeTransaction>
  <ram:IncludedSupplyChainTradeLineItem>
   <ram:AssociatedDocumentLineDocument><ram:LineID>10</ram:LineID></ram:AssociatedDocumentLineDocument>
   <ram:SpecifiedTradeProduct><ram:SellerAssignedID>SVC-10</ram:SellerAssignedID><ram:Name>Engineering service</ram:Name><ram:Description>Technical implementation and verification</ram:Description></ram:SpecifiedTradeProduct>
   <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount currencyID="EUR">125.00</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
   <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="HUR">4</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
   <ram:SpecifiedLineTradeSettlement><ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent></ram:ApplicableTradeTax><ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount currencyID="EUR">500.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>
  </ram:IncludedSupplyChainTradeLineItem>
  <ram:ApplicableHeaderTradeAgreement><ram:BuyerReference>BR-77</ram:BuyerReference>
   <ram:SellerTradeParty><ram:Name>CII Seller GmbH</ram:Name><ram:PostalTradeAddress><ram:PostcodeCode>50667</ram:PostcodeCode><ram:LineOne>Domstrasse 5</ram:LineOne><ram:CityName>Koeln</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress><ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE987654321</ram:ID></ram:SpecifiedTaxRegistration></ram:SellerTradeParty>
   <ram:BuyerTradeParty><ram:Name>CII Buyer AG</ram:Name><ram:PostalTradeAddress><ram:PostcodeCode>20095</ram:PostcodeCode><ram:LineOne>Hafenweg 2</ram:LineOne><ram:CityName>Hamburg</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress></ram:BuyerTradeParty>
   <ram:BuyerOrderReferencedDocument><ram:IssuerAssignedID>PO-CII-1</ram:IssuerAssignedID></ram:BuyerOrderReferencedDocument>
  </ram:ApplicableHeaderTradeAgreement>
  <ram:ApplicableHeaderTradeDelivery><ram:ActualDeliverySupplyChainEvent><ram:OccurrenceDateTime><ram:DateTimeString format="102">20261005</ram:DateTimeString></ram:OccurrenceDateTime></ram:ActualDeliverySupplyChainEvent></ram:ApplicableHeaderTradeDelivery>
  <ram:ApplicableHeaderTradeSettlement><ram:PaymentReference>CII-2026-0007</ram:PaymentReference><ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
   <ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>58</ram:TypeCode><ram:PayeePartyCreditorFinancialAccount><ram:IBANID>DE75512108001245126199</ram:IBANID></ram:PayeePartyCreditorFinancialAccount></ram:SpecifiedTradeSettlementPaymentMeans>
   <ram:ApplicableTradeTax><ram:CalculatedAmount currencyID="EUR">95.00</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode><ram:BasisAmount currencyID="EUR">500.00</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent></ram:ApplicableTradeTax>
   <ram:SpecifiedTradePaymentTerms><ram:Description>Pay within 14 days.</ram:Description><ram:DueDateDateTime><ram:DateTimeString format="102">20261020</ram:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
   <ram:SpecifiedTradeSettlementHeaderMonetarySummation><ram:LineTotalAmount currencyID="EUR">500.00</ram:LineTotalAmount><ram:TaxBasisTotalAmount currencyID="EUR">500.00</ram:TaxBasisTotalAmount><ram:TaxTotalAmount currencyID="EUR">95.00</ram:TaxTotalAmount><ram:GrandTotalAmount currencyID="EUR">595.00</ram:GrandTotalAmount><ram:DuePayableAmount currencyID="EUR">595.00</ram:DuePayableAmount></ram:SpecifiedTradeSettlementHeaderMonetarySummation>
   <ram:ReceivableSpecifiedTradeAccountingAccount><ram:ID>UNMAPPED-CII-ACCOUNT</ram:ID></ram:ReceivableSpecifiedTradeAccountingAccount>
  </ram:ApplicableHeaderTradeSettlement>
 </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""


@pytest.fixture
def ubl_credit_note_xml() -> bytes:
    return b"""<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
 <cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID><cbc:ID>CN-9</cbc:ID>
 <cbc:IssueDate>2026-10-06</cbc:IssueDate><cbc:CreditNoteTypeCode>381</cbc:CreditNoteTypeCode><cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
 <cac:CreditNoteLine><cbc:ID>1</cbc:ID><cbc:CreditedQuantity unitCode="C62">1</cbc:CreditedQuantity><cbc:LineExtensionAmount currencyID="EUR">25.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Returned item</cbc:Name></cac:Item><cac:Price><cbc:PriceAmount currencyID="EUR">25.00</cbc:PriceAmount></cac:Price></cac:CreditNoteLine>
 <cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="EUR">25.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</CreditNote>"""


@pytest.fixture
def make_pdf():
    def factory(
        attachments: list[tuple[str, bytes]],
        *,
        encrypt: bool = False,
        pdfa_part: str | None = None,
        pdfa_conformance: str = "B",
        relationships: dict[str, str] | None = None,
    ) -> bytes:
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        associated_files = ArrayObject()
        for filename, content in attachments:
            embedded = writer.add_attachment(filename, content)
            relationship = (relationships or {}).get(filename)
            if relationship:
                embedded.associated_file_relationship = NameObject(f"/{relationship}")
                associated_files.append(embedded.pdf_object.indirect_reference)
        if associated_files:
            writer.root_object[NameObject("/AF")] = associated_files
        if pdfa_part is not None:
            writer.xmp_metadata = f"""<?xpacket begin='' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/"
    pdfaid:part="{pdfa_part}" pdfaid:conformance="{pdfa_conformance}" />
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>""".encode("utf-8")
        if encrypt:
            writer.encrypt("secret")
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    return factory


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        max_pdf_bytes=2 * 1024 * 1024,
        max_xml_bytes=256 * 1024,
        max_attachment_total_bytes=2 * 1024 * 1024,
    )
    return TestClient(create_app(settings))
