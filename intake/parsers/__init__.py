"""File parsers. ``parse_file`` picks one by extension."""

from __future__ import annotations

from intake.parsers.base import ParsedFile

SPREADSHEET_EXT = (".csv", ".xlsx")
EMAIL_EXT = (".eml", ".txt")


def parse_file(filename: str, content: bytes) -> ParsedFile:
    name = filename.lower()
    if name.endswith(SPREADSHEET_EXT):
        from intake.parsers.spreadsheet import parse_spreadsheet

        return parse_spreadsheet(filename, content)
    if name.endswith(EMAIL_EXT):
        from intake.parsers.email import parse_email

        return parse_email(filename, content)
    return ParsedFile(kind="unknown", error=f"unsupported file type: {filename}")


__all__ = ["ParsedFile", "parse_file"]
