# Cash-flow source quality — 28 October 2026

Cash-flow Intelligence now asks how numeric statement dates should be read.
`03/04/2026` can mean 3 April or 4 March, changing retained months and financial
figures. The workspace offers Automatic, Day / Month / Year and Month / Day /
Year. Its result records the requested and resolved convention.

## Date interpretation

Automatic mode uses a valid, unambiguous numeric date anywhere in the source to
infer one convention for the whole file. For example, `27/01/2026` establishes
day-first. If both known conventions occur, the source is refused. If dates
remain ambiguous without a clue, the response lists up to ten physical CSV
record-ending lines and asks the user to choose the source convention. Dates
such as `02/02/2026` need no guess. Invalid dates are not inference clues.

The explicitly selected convention never falls back to the opposite convention.
Dates invalid under that selection stay unreadable in the canonical parser.
Its existing quality gate withholds forecasts for unreadable rows. ISO/year-first
and supported named-month dates keep their calendar meaning. Timestamps use the
source calendar date without timezone conversion. Two-digit years retain
Python strptime's existing interpretation; four-digit years are preferable.

Automatic inference assumes a consistent source convention; it cannot detect a
mixed file whose dates all happen to be valid under both conventions. Check the
bank/export specification when choosing. This inspection applies only to the
Cash-flow Intelligence workspace; the saved scoring statement parser and
historical evidence are unchanged.

## Repeated rows and structural checks

Exact parsed cell tuples across every source column identify repeated-row
candidates. The result counts all candidates and lists up to ten examples,
each referring to the first matching record and the repeated record. References
are physical record-ending lines, including quoted multiline cells.

**No rows are deduplicated.** Identical transactions can be legitimate; these
candidates are not a fraud finding. Candidates can include records subsequently
excluded by the parser. Figures include every record the canonical parser
accepts. Different references or other different cell values prevent an exact
row match; this is not fuzzy duplicate detection.

Headers must be present, nonempty and unique after canonical name cleaning.
Exactly one recognised date column is required. Malformed quotes and records
whose field counts differ from the header are refused with an actionable error.
The service does not echo cell contents in these errors.

## Audit and request safety

`cashflow-local-v2` adds `cashflow-import-v1` source-quality metadata. One SHA-256
identifies the exact decoded UTF-8 source text; another identifies the rewritten
CSV actually passed to the parser. The latter normalises valid dates to ISO,
writes LF record separators and preserves other parsed cell values. These are
content identities, not proof that a bank issued the statement.

Changing the source or date selection removes earlier results and aborts the
outstanding request. The client verifies source identity, requested date mode,
method version and report consistency before displaying a result. A new file,
Clear statement or the synthetic example resets date mode to Automatic. A file
read failure retains the earlier source and selection. No case is saved.

Forecast mathematics and the chronological development/calibration/evaluation
protocol are unchanged; see [the method description](cashflow-intelligence-2026-10-28.md).
This improvement adds no credit-model inputs, training, external AI calls or
validated SME risk claims.

## Verification

Windows and built Linux-image checks each passed 93 relevant backend tests.
Frontend checks passed 93 tests. Source inspection tests cover ambiguous dates,
both conventions, explicit-mode failures, identical dates, invalid dates,
malformed CSV, repeated records, bounded examples, BOM/CRLF and multiline line
references. Build, browser and deployment evidence is recorded in
`archive/cashflow-source-quality-2026-10-28/verification.md`.
