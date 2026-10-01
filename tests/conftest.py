from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

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
def make_pdf():
    def factory(attachments: list[tuple[str, bytes]], *, encrypt: bool = False) -> bytes:
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        for filename, content in attachments:
            writer.add_attachment(filename, content)
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
