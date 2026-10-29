# Reminder workflow review — 29 October 2026

The focused audit covered finding a reminder, checking its recorded evidence
and preparing a draft. The existing screen's schedule explanation and missing
month/unknown-amount warnings were useful. Its next actions went straight to
copying or opening WhatsApp, with no direct case/monitoring route or fresh-draft
check. It also lacked search and filters. These findings were captured in this
run's `archive/reminder-review-2026-10-29/01-before-reminders.jpg`.

## What changed

The list now has combined business/applicant or exact case-ID search, reminder
type filters, and checks for monitoring gaps, unknown payment amounts and an
unusable international contact number. Applied filters remain in the URL.
Counts clearly distinguish matching reminders from the whole fetched list.
Each card links directly to its monitoring facility and saved case.
Those destinations show **Back to reminders** with the same search and record
filters, rather than directing a reminder user to an unrelated Action Desk.
Return state is normalised to the three allowed filters; it cannot select an
external destination. Existing Action Desk return behaviour stays available.

**Review draft** re-reads the current authenticated reminder list before showing
text or a WhatsApp draft link. If the selected reminder has disappeared, the old
draft is withheld. Failed or malformed responses also withhold it and offer a
retry. A fresh response reconciles the list underneath the dialog, so changed
figures, contact details and removed reminders do not remain falsely current.
This is a fresh read of recorded information, not independent payment verification.

The review shows recorded principal installment, indicative date, recorded
arrears, current contact, data warnings and a client-clock time for the refresh.
The user can switch Roman Urdu/English, refresh again, copy the reviewed text
or open a WhatsApp draft. Payment or monitoring information can still change
after that read; there is no promise that the source remains current indefinitely.

Copy success and failure have explicit status/error feedback. A language change,
new refresh or dialog closure invalidates earlier pending copy feedback. Copying
or opening a draft does not create a sent-message record. Nothing sends itself.
The user checks agreed amounts, dates and receipts before choosing whether to
communicate. Actual sending was outside this audit and was not performed.

Only international digit-only numbers with an optional leading `+` produce a
WhatsApp link; message text is URL-encoded. This is a format check, not evidence
of ownership, reachability or borrower consent. Invalid/local-only numbers can
still be inspected in the review, but do not generate a misleading draft link.

## Reliability and accessibility

Aborted/superseded reads cannot replace a later result. Returned records need
unique case IDs, finite nonnegative money, valid dates, known kinds and
consistent due/arrears shapes before rendering. The existing backend remains
authoritative for schedules and reminder rules; no loan calculation changed.

The review uses the existing native modal, heading focus, keyboard containment
and focus restoration. Search results and copy success use status messages;
copy errors use an alert. This follows the narrow feedback principle described
in [W3C's Status Messages guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).
It is not a claim of full WCAG compliance or completed assistive-technology testing.

The update makes no backend, schema, role, model, loan or decision change.
Verification and audit screenshots are recorded in
`archive/reminder-review-2026-10-29/verification.md`.
