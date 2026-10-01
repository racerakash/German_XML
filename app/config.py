from __future__ import annotations

import os
from dataclasses import dataclass

MIB = 1024 * 1024


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    max_pdf_bytes: int = 25 * MIB
    max_xml_bytes: int = 10 * MIB
    max_attachment_total_bytes: int = 50 * MIB

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            max_pdf_bytes=_positive_int_from_env("MAX_PDF_BYTES", 25 * MIB),
            max_xml_bytes=_positive_int_from_env("MAX_XML_BYTES", 10 * MIB),
            max_attachment_total_bytes=_positive_int_from_env(
                "MAX_ATTACHMENT_TOTAL_BYTES", 50 * MIB
            ),
        )
