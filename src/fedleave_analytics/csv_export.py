"""Spreadsheet-oriented CSV text encoding; canonical records stay unchanged."""

import csv
import unicodedata


def spreadsheet_cell(value):
    if not isinstance(value, str) or not value:
        return value
    start = 0
    while start < len(value) and (value[start].isspace() or unicodedata.category(value[start]) in {"Cc", "Cf"}):
        start += 1
    # CSV quoting alone does not stop spreadsheet formula evaluation.
    if unicodedata.category(value[0]) in {"Cc", "Cf"} or value[start : start + 1] in {
        "=",
        "+",
        "-",
        "@",
        "＝",
        "＋",
        "－",
        "＠",
    }:
        return "'" + value
    return value


class SpreadsheetWriter:
    def __init__(self, handle):
        self._writer = csv.writer(handle)

    def writerow(self, row):
        return self._writer.writerow([spreadsheet_cell(value) for value in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)
