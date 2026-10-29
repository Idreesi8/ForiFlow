"""Explicit date interpretation and non-destructive CSV quality inspection.

Only the Cash-flow Intelligence path uses this adapter. The canonical scoring
parser and historical evidence stay unchanged. Hashes identify both the exact
decoded source text and the ISO-date-normalised CSV actually parsed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import replace
from datetime import datetime

from cashflow_schemas import SourceQuality
from services.statement_service import (
    DATE_COLUMNS, DATE_FORMATS, MAX_STATEMENT_CHARS, StatementError,
    _clean, parse_statement,
)

NUMERIC = re.compile(r'^(\d{1,2})([/\-])(\d{1,2})\2(\d{2}|\d{4})$')


def _token(value):
    return (value or '').strip().split('T')[0].split(' ')[0]


def _numeric_date(value, order):
    token = _token(value)
    match = NUMERIC.fullmatch(token)
    if not match:
        return None
    separator = match[2]
    year = '%Y' if len(match[4]) == 4 else '%y'
    pattern = ('%d'+separator+'%m' if order == 'day_first' else '%m'+separator+'%d')+separator+year
    try:
        return datetime.strptime(token, pattern).date()
    except ValueError:
        return None


def _other_date(value):
    text = (value or '').strip()
    for candidate in (text, text.split('T')[0], text.split(' ')[0]):
        for pattern in DATE_FORMATS:
            # Numeric day/month dates are handled exclusively by the selected
            # convention; never fall back to the other convention silently.
            if not pattern.startswith('%Y') and '%b' not in pattern:
                continue
            try:
                return datetime.strptime(candidate, pattern).date()
            except ValueError:
                pass
    return None


def prepare_source(source: str, date_order: str = 'auto'):
    if date_order not in ('auto', 'day_first', 'month_first'):
        raise StatementError('Choose automatic, day-first or month-first dates.')
    if len(source) > MAX_STATEMENT_CHARS:
        raise StatementError('The statement exceeds 2 MB. Export a shorter period.')
    try:
        return _prepare(source, date_order)
    except csv.Error:
        raise StatementError('The CSV could not be read. Check quotes and field lengths, then export again.') from None


def _prepare(source, requested):
    reader = csv.DictReader(io.StringIO(source.lstrip('\ufeff')), strict=True)
    header = reader.fieldnames or []
    cleaned = [_clean(name) for name in header]
    if not header or any(not name for name in cleaned) or len(set(cleaned)) != len(cleaned):
        raise StatementError('CSV headers must be present, nonempty and unique. Rename repeated columns before importing.')
    dates = [name for name in header if _clean(name) in DATE_COLUMNS]
    if len(dates) != 1:
        raise StatementError('Keep exactly one recognised date column (for example date or transaction date). Choose the relevant date in the export.')
    date_column = dates[0]
    rows, inferred, ambiguous = [], set(), []
    seen, repeated, repeat_count = {}, [], 0
    identical_valid_rows = 0
    for row in reader:
        line = reader.line_num
        if None in row or any(value is None for value in row.values()):
            raise StatementError(f'CSV line {line} has a different number of fields from the header. Check commas and quoted values.')
        signature = tuple(row[name] for name in header)
        if signature in seen:
            repeat_count += 1
            if len(repeated) < 10:
                repeated.append({'first_line': seen[signature], 'repeated_line': line})
        else:
            seen[signature] = line
        raw_date = row[date_column]
        numeric = NUMERIC.fullmatch(_token(raw_date)) is not None
        if numeric:
            day, month = _numeric_date(raw_date, 'day_first'), _numeric_date(raw_date, 'month_first')
            if day and month and day != month:
                ambiguous.append(line)
            elif bool(day) != bool(month):
                inferred.add('day_first' if day else 'month_first')
            elif day is not None and day == month:
                identical_valid_rows += 1
        rows.append(row)
    if requested == 'auto':
        if len(inferred) > 1:
            raise StatementError('The CSV mixes day-first and month-first numeric dates. Standardise the date column to YYYY-MM-DD before importing.')
        if inferred:
            resolved = next(iter(inferred))
        elif ambiguous:
            locations = ', '.join(map(str, ambiguous[:10]))
            raise StatementError(f'Ambiguous numeric dates at CSV line(s) {locations}. Select Day / Month / Year or Month / Day / Year to match the source; automatic mode will not guess.')
        else:
            resolved = 'identical_day_month' if identical_valid_rows else 'iso_or_named'
    else:
        resolved = requested
    normalised = 0
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=header, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        raw_date = row[date_column]
        if NUMERIC.fullmatch(_token(raw_date)):
            parsed = _numeric_date(raw_date, resolved if resolved in ('day_first', 'month_first') else 'day_first')
        else:
            parsed = _other_date(raw_date)
        # Invalid dates stay unreadable in the canonical parser. In particular,
        # a wrong explicitly selected numeric convention must not be re-guessed.
        replacement = parsed.isoformat() if parsed else 'UNREADABLE_DATE'
        normalised += int(parsed is not None and replacement != raw_date)
        row[date_column] = replacement
        writer.writerow(row)
    parsed_text = output.getvalue()
    if len(parsed_text) > MAX_STATEMENT_CHARS:
        raise StatementError('The normalised CSV exceeds 2 MB. Export a shorter period.')
    summary = parse_statement(parsed_text)
    notes = [
        'The selected date convention applies to numeric day/month dates. ISO and named-month dates remain unambiguous; timestamps are treated as source calendar dates, without timezone conversion.',
        'Automatic inference assumes one convention across the file. A later-accepted unambiguous date can resolve earlier ambiguous dates; mixed known conventions are refused.',
        'Repeated-row candidates have identical cell values across every column. They may be legitimate repeated transactions and can include rows excluded by the parser. They are not proof of duplication or fraud.',
        'No repeated rows are deleted or deduplicated. Historical figures and forecasts use every row accepted by the canonical parser; verify candidates against the original export.',
        'CSV line references identify the physical line where a record ends; quoted multiline cells can make a record span several lines.',
    ]
    quality = SourceQuality(date_order_requested=requested, date_order_resolved=resolved,
        ambiguous_numeric_rows=len(ambiguous), normalised_date_rows=normalised,
        source_rows=len(rows), repeated_row_candidates=repeat_count,
        repeated_row_examples=repeated, parsed_source_sha256=summary.source_sha256, notes=notes)
    warnings = list(summary.warnings)
    if repeat_count:
        warnings.append(f'{repeat_count} repeated CSV row candidate(s) have identical cell values. No rows were removed; compare the listed lines with the source before using the figures.')
    # Preserve both fingerprints: raw source for request matching; the audit
    # retains the actual ISO-normalised bytes handed to the canonical parser.
    return replace(summary, source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(), warnings=warnings), quality
