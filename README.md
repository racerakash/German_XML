# German E-Invoice Extractor

A stateless FastAPI service and local CLI for extracting embedded XML and other attachments from PDFs, identifying ZUGFeRD/Factur-X, XRechnung, EN 16931, CII, and UBL invoice documents, and rendering recognized XML as a readable PDF.

The API always returns the original PDF unchanged. It does not persist uploaded data. Full XSD and Schematron compliance validation is intentionally out of scope.

## Requirements and setup

- Python 3.11 or newer

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

macOS/Linux:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Run the API:

```bash
uvicorn app.api:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive OpenAPI UI. Health is available at `GET /healthz`.

## API

### Extract a PDF

`POST /v1/pdf/extract`

```json
{
  "content_base64": "JVBERi0xLj...",
  "filename": "invoice.pdf"
}
```

The response contains a UUID `identifier`, the unchanged PDF, the one embedded XML attachment and its classification, plus all non-XML attachments. Every file is returned as base64 with its byte size and SHA-256. More than one XML attachment is rejected as ambiguous.

PowerShell example:

```powershell
$bytes = [System.IO.File]::ReadAllBytes("C:\invoices\invoice.pdf")
$body = @{ content_base64 = [Convert]::ToBase64String($bytes); filename = "invoice.pdf" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/pdf/extract" -ContentType "application/json" -Body $body
```

curl example:

```bash
PDF_B64="$(base64 < invoice.pdf | tr -d '\n')"
curl -sS http://127.0.0.1:8000/v1/pdf/extract \
  -H 'Content-Type: application/json' \
  -d "{\"content_base64\":\"$PDF_B64\",\"filename\":\"invoice.pdf\"}"
```

### Check PDF/A-3, ZUGFeRD, and attachments

`POST /v1/pdf/check` accepts the same strict-base64 PDF request without extracting attachment content into the response:

```json
{
  "content_base64": "JVBERi0xLj...",
  "filename": "invoice.pdf"
}
```

Example response fields:

```json
{
  "identifier": "2ee172bb-f2b2-4e34-935b-1ee414228e9d",
  "filename": "invoice.pdf",
  "is_pdfa3_or_zugferd_with_xml": true,
  "is_pdfa3": true,
  "pdfa_part": "3",
  "pdfa_conformance": "B",
  "pdfa_detection": "XMP_METADATA_CLAIM",
  "has_xml_attachment": true,
  "is_zugferd": true,
  "attachments": [
    {
      "filename": "factur-x.xml",
      "media_type": "application/xml",
      "attachment_type": "CII",
      "association_relationship": "Alternative",
      "size_bytes": 1234,
      "sha256": "...",
      "classification": {
        "syntax": "CII",
        "standard": "ZUGFERD_FACTUR_X"
      }
    }
  ]
}
```

Attachment types are `CII`, `UBL`, `XML`, or `OTHER`. The overall boolean is true only when the PDF contains an XML attachment and either declares PDF/A-3 in XMP or contains XML classified as ZUGFeRD/Factur-X. The PDF/A result is an XMP metadata claim check, not full ISO 19005-3 conformance validation; use a dedicated validator such as veraPDF when formal compliance proof is required.

### Identify XML

`POST /v1/xml/identify` uses the same JSON shape. It returns the UUID, hash, and classification without echoing the XML. Well-formed unrelated XML returns HTTP 200 with `syntax: "UNKNOWN"`; malformed XML returns 422.

Each API response includes the UUID in both `identifier` and the `X-Request-ID` response header. Console logs contain the UUID, endpoint, CII/UBL type, standard, profile, and outcome but never the supplied content.

### Render XML as PDF

`POST /v1/xml/render-pdf` uses the same strict-base64 JSON request:

```json
{
  "content_base64": "PD94bWwgdmVyc2lvbj0iMS4wIj8+...",
  "filename": "invoice.xml"
}
```

The response includes the UUID, XML classification, and a base64 PDF with filename, MIME type, size, and SHA-256. The renderer creates an English A4 invoice with parties, references, delivery and payment details, line items, taxes, totals, and notes. A deterministic appendix includes XML scalar values and attributes not already displayed; binary objects are represented by filename/MIME metadata, decoded size, and SHA-256 instead of their base64 payload.

PowerShell example:

```powershell
$bytes = [System.IO.File]::ReadAllBytes("C:\invoices\invoice.xml")
$body = @{ content_base64 = [Convert]::ToBase64String($bytes); filename = "invoice.xml" } | ConvertTo-Json
$response = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/xml/render-pdf" -ContentType "application/json" -Body $body
[System.IO.File]::WriteAllBytes("invoice.pdf", [Convert]::FromBase64String($response.pdf.content_base64))
```

Supported UBL roots are `Invoice`, `CreditNote`, `DebitNote`, `SelfBilledInvoice`, and `SelfBilledCreditNote`. CII `CrossIndustryInvoice` documents and UN/EDIFACT document type codes are rendered with appropriate headings, including commercial, corrected, prepayment, debit, credit, self-billed, partial, tax, hire, freight, and construction invoices. An unknown type code is still rendered and shown explicitly in the heading.

The generated PDF is an informational visualization only. It is not PDF/A-3, does not embed the source XML, and must not be described as a conformant ZUGFeRD/Factur-X hybrid. The original XML remains the authoritative structured invoice.

## Local CLI

Identify XML:

```bash
invoice-extractor identify-xml path/to/invoice.xml
```

Render CII or UBL XML to PDF:

```bash
invoice-extractor render-pdf path/to/invoice.xml --output invoice.pdf
```

Extract one PDF into a per-PDF output directory:

```bash
invoice-extractor extract path/to/invoice.pdf --output output
```

Check PDF/A-3/ZUGFeRD status and list attachment filenames and types without saving them:

```bash
invoice-extractor check-pdf path/to/invoice.pdf
```

Example console output:

```text
identifier=... source=invoice.pdf is_pdfa3_or_zugferd_with_xml=True is_pdfa3=True pdfa_part=3 pdfa_conformance=B has_xml_attachment=True is_zugferd=True
attachment filename=factur-x.xml type=CII media_type=application/xml relationship=Alternative syntax=CII standard=ZUGFERD_FACTUR_X
```

Process a directory, optionally recursively:

```bash
invoice-extractor batch path/to/zugferd-samples --output output --recursive
```

The CLI saves embedded XML and non-XML attachments, sanitizes names, avoids overwrites, and prints each request UUID and detected syntax.

## Limits

Defaults can be overridden with environment variables:

| Variable | Default |
| --- | ---: |
| `MAX_PDF_BYTES` | 26214400 (25 MiB) |
| `MAX_XML_BYTES` | 10485760 (10 MiB) |
| `MAX_ATTACHMENT_TOTAL_BYTES` | 52428800 (50 MiB) |

Input base64 is strict: whitespace and data URI prefixes are rejected. Encrypted PDFs are not supported.

## Tests

```bash
pytest
```

The automated suite generates small PDFs in memory and requires no network access. To test official files, download the current ZUGFeRD information package from [FeRD](https://www.ferd-net.de/en/download-zugferd), extract it locally, and run:

```bash
invoice-extractor batch path/to/extracted-package --output output --recursive
```

This performs extraction and identification only; it is not full KoSIT, XSD, or Schematron validation.

## Example output

The repository includes `examples/sample-ubl-invoice.xml`. Render it locally with:

```bash
invoice-extractor render-pdf examples/sample-ubl-invoice.xml --output output/pdf/sample-ubl-invoice.pdf
```
