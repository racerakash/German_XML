from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.encoding import sha256_hex
from app.errors import ServiceError
from app.invoice_renderer import render_invoice_pdf
from app.service import PdfExtractionResult, process_pdf
from app.xml_identifier import identify_xml

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(value: str, fallback: str) -> str:
    name = Path(value.replace("\\", "/")).name
    name = INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
    return name or fallback


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    counter = 2
    while candidate.exists():
        candidate = directory / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
        counter += 1
    return candidate


def _write_attachments(
    source: Path, output_root: Path, result: PdfExtractionResult
) -> list[Path]:
    directory_name = _safe_filename(source.stem, "invoice")
    directory = output_root / directory_name
    suffix = 2
    while directory.exists() and any(directory.iterdir()):
        directory = output_root / f"{directory_name}_{suffix}"
        suffix += 1
    directory.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    attachments = [result.xml_attachment, *result.other_attachments]
    for index, attachment in enumerate(attachments, start=1):
        safe_name = _safe_filename(attachment.filename, f"attachment-{index}")
        target = _unique_path(directory, safe_name)
        target.write_bytes(attachment.content)
        written.append(target)
    return written


def _print_pdf_result(identifier: str, source: Path, result: PdfExtractionResult) -> None:
    classification = result.xml_classification
    print(
        f"identifier={identifier} source={source} syntax={classification.syntax.value} "
        f"standard={classification.standard.value} profile={classification.profile or '-'}"
    )


def _process_pdf_file(source: Path, output_root: Path, settings: Settings) -> None:
    identifier = str(uuid4())
    pdf_bytes = source.read_bytes()
    if len(pdf_bytes) > settings.max_pdf_bytes:
        raise ServiceError(
            "payload_too_large",
            "PDF exceeds the configured size limit",
            status_code=413,
            details={"max_bytes": settings.max_pdf_bytes},
        )
    result = process_pdf(pdf_bytes, settings)
    written = _write_attachments(source, output_root, result)
    _print_pdf_result(identifier, source, result)
    for path in written:
        print(f"saved={path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="invoice-extractor",
        description="Identify XML and extract attachments from German e-invoice PDFs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    identify_parser = subparsers.add_parser("identify-xml", help="Identify an XML file")
    identify_parser.add_argument("xml_file", type=Path)

    render_parser = subparsers.add_parser(
        "render-pdf", help="Render CII or UBL XML as a readable PDF"
    )
    render_parser.add_argument("xml_file", type=Path)
    render_parser.add_argument("--output", "-o", type=Path, required=True)

    extract_parser = subparsers.add_parser("extract", help="Extract one PDF")
    extract_parser.add_argument("pdf_file", type=Path)
    extract_parser.add_argument("--output", "-o", type=Path, required=True)

    batch_parser = subparsers.add_parser("batch", help="Extract every PDF in a directory")
    batch_parser.add_argument("input_directory", type=Path)
    batch_parser.add_argument("--output", "-o", type=Path, required=True)
    batch_parser.add_argument("--recursive", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()

    try:
        if args.command == "identify-xml":
            content = args.xml_file.read_bytes()
            if len(content) > settings.max_xml_bytes:
                raise ServiceError(
                    "payload_too_large",
                    "XML exceeds the configured size limit",
                    status_code=413,
                )
            identifier = str(uuid4())
            classification = identify_xml(content)
            print(
                f"identifier={identifier} source={args.xml_file} "
                f"syntax={classification.syntax.value} standard={classification.standard.value} "
                f"profile={classification.profile or '-'} sha256={sha256_hex(content)}"
            )
            return 0

        if args.command == "render-pdf":
            content = args.xml_file.read_bytes()
            if len(content) > settings.max_xml_bytes:
                raise ServiceError(
                    "payload_too_large",
                    "XML exceeds the configured size limit",
                    status_code=413,
                    details={"max_bytes": settings.max_xml_bytes},
                )
            identifier = str(uuid4())
            pdf_bytes, classification = render_invoice_pdf(content)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(pdf_bytes)
            print(
                f"identifier={identifier} source={args.xml_file} "
                f"syntax={classification.syntax.value} standard={classification.standard.value} "
                f"profile={classification.profile or '-'} saved={args.output}"
            )
            return 0

        if args.command == "extract":
            _process_pdf_file(args.pdf_file, args.output, settings)
            return 0

        pattern = "**/*.pdf" if args.recursive else "*.pdf"
        sources = sorted(args.input_directory.glob(pattern))
        if not sources:
            print("No PDF files found", file=sys.stderr)
            return 1
        failed = False
        for source in sources:
            try:
                _process_pdf_file(source, args.output, settings)
            except (OSError, ServiceError) as exc:
                failed = True
                code = exc.code if isinstance(exc, ServiceError) else "file_error"
                print(f"source={source} outcome=error code={code} message={exc}", file=sys.stderr)
        return 1 if failed else 0
    except (OSError, ServiceError) as exc:
        code = exc.code if isinstance(exc, ServiceError) else "file_error"
        print(f"outcome=error code={code} message={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
