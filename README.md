# German E-Invoice Extractor

A stateless FastAPI service and local CLI for extracting embedded XML and other attachments from PDFs, then identifying ZUGFeRD/Factur-X, XRechnung, EN 16931, CII, and UBL invoice documents.

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

### Identify XML

`POST /v1/xml/identify` uses the same JSON shape. It returns the UUID, hash, and classification without echoing the XML. Well-formed unrelated XML returns HTTP 200 with `syntax: "UNKNOWN"`; malformed XML returns 422.

Each API response includes the UUID in both `identifier` and the `X-Request-ID` response header. Console logs contain the UUID, endpoint, CII/UBL type, standard, profile, and outcome but never the supplied content.

## Local CLI

Identify XML:

```bash
invoice-extractor identify-xml path/to/invoice.xml
```

Extract one PDF into a per-PDF output directory:

```bash
invoice-extractor extract path/to/invoice.pdf --output output
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
