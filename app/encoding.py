from __future__ import annotations

import base64
import binascii
import hashlib

from app.errors import ServiceError


def decode_base64_strict(value: str, *, max_bytes: int, kind: str) -> bytes:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ServiceError(
            "invalid_base64", f"{kind} content must be ASCII base64"
        ) from exc

    estimated_size = (len(encoded) * 3) // 4
    if estimated_size > max_bytes + 2:
        raise ServiceError(
            "payload_too_large",
            f"Decoded {kind} exceeds the configured size limit",
            status_code=413,
            details={"max_bytes": max_bytes},
        )

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ServiceError(
            "invalid_base64", f"{kind} content is not valid strict base64"
        ) from exc

    if len(decoded) > max_bytes:
        raise ServiceError(
            "payload_too_large",
            f"Decoded {kind} exceeds the configured size limit",
            status_code=413,
            details={"max_bytes": max_bytes},
        )
    return decoded


def encode_base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
