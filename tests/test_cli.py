from __future__ import annotations

from pathlib import Path

from app.cli import main


def test_cli_extract_saves_sanitized_unique_attachments(
    tmp_path: Path, make_pdf, cii_xml: bytes, capsys
) -> None:
    source = tmp_path / "invoice.pdf"
    source.write_bytes(
        make_pdf(
            [
                ("factur-x.xml", cii_xml),
                ("../terms.txt", b"first"),
                ("terms.txt", b"second"),
            ]
        )
    )
    output = tmp_path / "output"
    assert main(["extract", str(source), "--output", str(output)]) == 0
    written = sorted((output / "invoice").iterdir())
    assert [path.name for path in written] == ["factur-x.xml", "terms.txt", "terms_2.txt"]
    assert {path.read_bytes() for path in written[1:]} == {b"first", b"second"}
    captured = capsys.readouterr()
    assert "syntax=CII" in captured.out
    assert "identifier=" in captured.out


def test_cli_identify_xml(tmp_path: Path, ubl_xml: bytes, capsys) -> None:
    source = tmp_path / "invoice.xml"
    source.write_bytes(ubl_xml)
    assert main(["identify-xml", str(source)]) == 0
    assert "syntax=UBL" in capsys.readouterr().out


def test_cli_batch_reports_failure_and_continues(
    tmp_path: Path, make_pdf, cii_xml: bytes, capsys
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "good.pdf").write_bytes(make_pdf([("invoice.xml", cii_xml)]))
    (inputs / "bad.pdf").write_bytes(b"not a pdf")
    exit_code = main(["batch", str(inputs), "--output", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "source=" in captured.err
    assert "syntax=CII" in captured.out
