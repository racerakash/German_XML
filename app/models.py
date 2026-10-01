from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class XmlSyntax(str, Enum):
    CII = "CII"
    UBL = "UBL"
    UNKNOWN = "UNKNOWN"


class InvoiceStandard(str, Enum):
    ZUGFERD_FACTUR_X = "ZUGFERD_FACTUR_X"
    XRECHNUNG = "XRECHNUNG"
    EN16931 = "EN16931"
    UNKNOWN = "UNKNOWN"


class Base64Request(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False, extra="forbid")

    content_base64: str = Field(min_length=1)
    filename: str | None = Field(default=None, max_length=255)


class XmlClassification(BaseModel):
    syntax: XmlSyntax
    standard: InvoiceStandard
    profile: str | None = None
    version: str | None = None
    document_type: str
    root_element: str
    guideline_identifier: str | None = None


class FilePayload(BaseModel):
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    content_base64: str


class XmlPayload(FilePayload):
    classification: XmlClassification


class PdfExtractResponse(BaseModel):
    identifier: str
    pdf: FilePayload
    xml: XmlPayload
    attachments: list[FilePayload]


class XmlIdentifyResponse(BaseModel):
    identifier: str
    filename: str | None
    size_bytes: int
    sha256: str
    classification: XmlClassification


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    identifier: str
    error: ErrorBody
