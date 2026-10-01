from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.config import Settings
from app.encoding import decode_base64_strict, encode_base64, sha256_hex
from app.errors import ServiceError
from app.models import (
    Base64Request,
    ErrorResponse,
    FilePayload,
    InvoiceStandard,
    PdfExtractResponse,
    XmlClassification,
    XmlIdentifyResponse,
    XmlPayload,
    XmlSyntax,
)
from app.service import process_pdf
from app.xml_identifier import identify_xml

logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)


def _identifier(request: Request) -> str:
    return str(request.state.identifier)


def _log_result(
    request: Request,
    *,
    outcome: str,
    classification: XmlClassification | None = None,
    code: str | None = None,
) -> None:
    if getattr(request.state, "result_logged", False):
        return
    request.state.result_logged = True
    syntax = classification.syntax.value if classification else "UNKNOWN"
    standard = classification.standard.value if classification else "UNKNOWN"
    profile = classification.profile if classification and classification.profile else "-"
    logger.info(
        "request_id=%s endpoint=%s xml_syntax=%s standard=%s profile=%s outcome=%s code=%s",
        _identifier(request),
        request.url.path,
        syntax,
        standard,
        profile,
        outcome,
        code or "-",
    )


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    _log_result(request, outcome="error", code=code)
    body = ErrorResponse(
        identifier=_identifier(request),
        error={"code": code, "message": message, "details": details or {}},
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": _identifier(request)},
    )


def _file_payload(filename: str, media_type: str, content: bytes) -> FilePayload:
    return FilePayload(
        filename=filename,
        media_type=media_type,
        size_bytes=len(content),
        sha256=sha256_hex(content),
        content_base64=encode_base64(content),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or Settings.from_env()
    app = FastAPI(
        title="German E-Invoice Extractor API",
        version=__version__,
        description="Extract and identify ZUGFeRD, Factur-X, and XRechnung XML.",
    )
    app.state.settings = active_settings

    @app.middleware("http")
    async def request_identifier_middleware(request: Request, call_next: Any):
        request.state.identifier = uuid4()
        request.state.result_logged = False
        response = await call_next(request)
        response.headers["X-Request-ID"] = _identifier(request)
        return response

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return _error_response(
            request,
            status_code=422,
            code="invalid_request",
            message="Request body failed validation",
            details={"errors": safe_errors},
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code="http_error",
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled request failure request_id=%s", _identifier(request))
        return _error_response(
            request,
            status_code=500,
            code="internal_error",
            message="An unexpected error occurred",
        )

    error_responses = {
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    }

    @app.get("/healthz", tags=["Operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post(
        "/v1/xml/identify",
        response_model=XmlIdentifyResponse,
        responses=error_responses,
        tags=["XML"],
    )
    async def identify_xml_endpoint(
        payload: Base64Request, request: Request
    ) -> XmlIdentifyResponse:
        xml_bytes = decode_base64_strict(
            payload.content_base64,
            max_bytes=active_settings.max_xml_bytes,
            kind="XML",
        )
        classification = identify_xml(xml_bytes)
        _log_result(request, outcome="success", classification=classification)
        return XmlIdentifyResponse(
            identifier=_identifier(request),
            filename=payload.filename,
            size_bytes=len(xml_bytes),
            sha256=sha256_hex(xml_bytes),
            classification=classification,
        )

    @app.post(
        "/v1/pdf/extract",
        response_model=PdfExtractResponse,
        responses=error_responses,
        tags=["PDF"],
    )
    async def extract_pdf_endpoint(
        payload: Base64Request, request: Request
    ) -> PdfExtractResponse:
        pdf_bytes = decode_base64_strict(
            payload.content_base64,
            max_bytes=active_settings.max_pdf_bytes,
            kind="PDF",
        )
        result = process_pdf(pdf_bytes, active_settings)
        pdf_name = payload.filename or "invoice.pdf"
        xml_file = _file_payload(
            result.xml_attachment.filename,
            result.xml_attachment.media_type,
            result.xml_attachment.content,
        )
        _log_result(request, outcome="success", classification=result.xml_classification)
        return PdfExtractResponse(
            identifier=_identifier(request),
            pdf=_file_payload(pdf_name, "application/pdf", pdf_bytes),
            xml=XmlPayload(
                **xml_file.model_dump(), classification=result.xml_classification
            ),
            attachments=[
                _file_payload(item.filename, item.media_type, item.content)
                for item in result.other_attachments
            ],
        )

    return app


app = create_app()
