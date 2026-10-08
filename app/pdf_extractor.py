from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Iterable

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from app.errors import ServiceError


@dataclass(frozen=True, slots=True)
class ExtractedAttachment:
    filename: str
    content: bytes
    media_type: str
    association_relationship: str | None = None


def _resolve(value: Any) -> Any:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _object_key(value: Any) -> tuple[str, int, int] | tuple[str, int]:
    if isinstance(value, IndirectObject):
        return ("ref", value.idnum, value.generation)
    reference = getattr(value, "indirect_reference", None)
    if isinstance(reference, IndirectObject):
        return ("ref", reference.idnum, reference.generation)
    return ("object", id(value))


def _decode_pdf_name(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _media_type_from_stream(stream: Any, filename: str) -> str:
    subtype = stream.get("/Subtype") if hasattr(stream, "get") else None
    if subtype:
        value = str(subtype).lstrip("/").replace("#2F", "/")
        if "/" in value:
            return value
    lowered = filename.lower()
    if lowered.endswith(".xml"):
        return "application/xml"
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"


def _attachment_from_filespec(value: Any, fallback_name: str) -> ExtractedAttachment | None:
    filespec = _resolve(value)
    if not isinstance(filespec, DictionaryObject):
        return None
    filename = _decode_pdf_name(filespec.get("/UF") or filespec.get("/F"), fallback_name)
    embedded_files = _resolve(filespec.get("/EF"))
    if not isinstance(embedded_files, DictionaryObject):
        return None
    stream_ref = embedded_files.get("/UF") or embedded_files.get("/F")
    if stream_ref is None:
        return None
    stream = _resolve(stream_ref)
    if not hasattr(stream, "get_data"):
        return None
    try:
        content = stream.get_data()
    except Exception as exc:
        raise ServiceError(
            "attachment_read_failed",
            f"Could not decode embedded attachment {filename!r}",
        ) from exc
    return ExtractedAttachment(
        filename=filename,
        content=content,
        media_type=_media_type_from_stream(stream, filename),
        association_relationship=(
            str(filespec.get("/AFRelationship")).lstrip("/")
            if filespec.get("/AFRelationship") is not None
            else None
        ),
    )


def _walk_name_tree(node_value: Any) -> Iterable[tuple[str, Any]]:
    node = _resolve(node_value)
    if not isinstance(node, DictionaryObject):
        return
    names = _resolve(node.get("/Names"))
    if isinstance(names, ArrayObject):
        for index in range(0, len(names) - 1, 2):
            yield _decode_pdf_name(_resolve(names[index]), f"attachment-{index // 2 + 1}"), names[index + 1]
    kids = _resolve(node.get("/Kids"))
    if isinstance(kids, ArrayObject):
        for child in kids:
            yield from _walk_name_tree(child)


def _array_values(value: Any) -> Iterable[Any]:
    resolved = _resolve(value)
    if isinstance(resolved, ArrayObject):
        yield from resolved


def extract_attachments(pdf_bytes: bytes, *, max_total_bytes: int) -> list[ExtractedAttachment]:
    if b"%PDF-" not in pdf_bytes[:1024]:
        raise ServiceError("invalid_pdf", "Content does not have a PDF header")

    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
    except (PdfReadError, ValueError, TypeError, OSError) as exc:
        raise ServiceError("invalid_pdf", "PDF content could not be parsed") from exc
    except Exception as exc:
        raise ServiceError("invalid_pdf", "PDF content could not be parsed") from exc

    if reader.is_encrypted:
        raise ServiceError("encrypted_pdf", "Encrypted PDFs are not supported")

    references: list[tuple[str, Any]] = []
    try:
        root = _resolve(reader.trailer["/Root"])
        names = _resolve(root.get("/Names")) if isinstance(root, DictionaryObject) else None
        embedded_tree = _resolve(names.get("/EmbeddedFiles")) if isinstance(names, DictionaryObject) else None
        if embedded_tree is not None:
            references.extend(_walk_name_tree(embedded_tree))

        if isinstance(root, DictionaryObject):
            for index, filespec in enumerate(_array_values(root.get("/AF")), start=1):
                references.append((f"associated-file-{index}", filespec))

        for page_number, page in enumerate(reader.pages, start=1):
            for index, filespec in enumerate(_array_values(page.get("/AF")), start=1):
                references.append((f"page-{page_number}-associated-file-{index}", filespec))
            for annotation in _array_values(page.get("/Annots")):
                resolved_annotation = _resolve(annotation)
                if not isinstance(resolved_annotation, DictionaryObject):
                    continue
                if str(resolved_annotation.get("/Subtype")) == "/FileAttachment" and resolved_annotation.get("/FS") is not None:
                    references.append((f"page-{page_number}-attachment", resolved_annotation.get("/FS")))
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError("invalid_pdf", "PDF attachment structure could not be read") from exc

    extracted: list[ExtractedAttachment] = []
    seen: set[tuple[str, int, int] | tuple[str, int]] = set()
    total_bytes = 0
    for fallback_name, reference in references:
        key = _object_key(reference)
        if key in seen:
            continue
        seen.add(key)
        attachment = _attachment_from_filespec(reference, fallback_name)
        if attachment is None:
            continue
        total_bytes += len(attachment.content)
        if total_bytes > max_total_bytes:
            raise ServiceError(
                "attachments_too_large",
                "Total decoded attachment data exceeds the configured size limit",
                status_code=413,
                details={"max_bytes": max_total_bytes},
            )
        extracted.append(attachment)
    return extracted


def looks_like_xml(attachment: ExtractedAttachment) -> bool:
    if attachment.filename.lower().endswith(".xml"):
        return True
    content = attachment.content
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    return content.lstrip().startswith(b"<")
