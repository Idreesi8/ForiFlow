# Complete monitoring lookup

The alert queue now searches and filters the complete stored queue, with bounded
database pages. A resolved alert remains discoverable even when more than 200
open alerts precede it in priority order.

`GET /ews/alert-queue` accepts `search` (up to 120 characters), `facility_id`,
`severity`, `alert_status`, `open_only`, `limit` (1–200), and `offset`. It returns
`items`, `total`, `matching`, `counts`, `limit`, and `offset`.

- `total` and `counts` cover the search, facility and severity scope across all statuses.
- `matching` also applies the selected lifecycle status and `open_only`.
- Counts include open, critical open, overdue open, closed, and the largest open score drop.
- Search matches business or applicant text, or an exact facility number, optionally prefixed with `#`.
- `%`, `_` and `!` are literal search characters. They are not wildcards.
- Priority remains open first, then severity, score drop, newest raised time, and ID.
- The existing list-shaped `GET /ews/alerts` remains available with the same parameters and ordering.

The monitoring selector uses the complete approved application register in pages
of 25. Searching or paging keeps the selected facility available and preserves
unsubmitted figures. Changing the facility still requires the existing discard
confirmation when figures are unsubmitted. An old facility can also be opened
directly by its case link.

Shared displays keep missing, malformed and non-finite figures unknown (`—`),
rather than converting blank strings or booleans to zero. Numeric zero remains
valid. Impossible calendar dates inside timestamps are rejected; future relative
times are labelled as future. Dates and times continue to use Pakistan time.

This changes retrieval and presentation. It adds no monitoring records, inferred
payments, trained models, or credit decisions. Counts are snapshots of stored
records and can change when another officer updates the queue.
