# Dated repayment calendar

The Early Warning workspace now has a separate repayment calendar for each
approved application. It records contractual dates and amounts and explicit
payment allocations. It does not move money, verify bank payments, change a
credit decision, rescore an applicant or generate monthly EWS observations.

## Recording a contract

A manager or admin records the actual disbursement date, agreed due dates and
amounts, and an agreement reference. The date is an officer assertion, not proof
that funds moved. A dated officer approval, when available, cannot be followed
by an earlier disbursement date. Legacy approved facilities can be entered from
their agreement without inventing an officer-approval timestamp.

Monthly preparation is an editable draft. It repeats the **entered agreed
amount**, retains the first due date's day-of-month (clamping to month-end),
and supports a different final amount or completely custom dates. It does not
derive interest, fees or instalments from the principal. Amounts may include
whatever the recorded agreement schedules; they are not a principal balance or
settlement quote. Due dates must be strictly increasing and not predate
disbursement. Up to 120 instalments are supported.

Replacing a schedule creates another immutable version and retains the previous
version and its provenance. The screen can read superseded versions, clearly
labelled as historical references. Replacement is refused while any receipt on
the current schedule remains active. Voiding is for correcting erroneous
records; it should not be used to discard valid repayments during restructuring.
Restructuring with transfer of valid allocations is not implemented.

## Receipts and corrections

Any enabled officer can record a payment date, evidence reference and explicit
allocation across one or more instalments. No automatic FIFO allocation is
assumed. The server rejects unknown instalments, duplicate allocation lines,
future payments, payments before the recorded disbursement and amounts exceeding
an instalment's unpaid balance. Payments before an instalment's due date are
allowed. A receipt reference, trimmed and uppercased, can appear only once among
the facility's active receipts. Split one payment across instalments in a single
receipt instead of recording the same reference repeatedly.

A manager can void an erroneous receipt with a reason. It remains visible with
its original amounts, allocations, actor and timestamp, plus who voided it and
why. Voiding restores the affected scheduled balances. A corrected receipt is a
new entry; the original is never deleted. History is paged, including older
receipts that may need correction. Capacity is 1,000 receipts per schedule and
100 schedule versions per facility; the API refuses additional writes beyond
these explicit limits.

## Arithmetic and interpretation

- Store monetary allocations as integer **paisa**, and return PKR as decimal
  strings. Reject more than two decimal places instead of rounding silently.
- Outstanding scheduled amount = scheduled amount minus active recorded
  allocations. Unrecorded payments cannot be inferred.
- For an unpaid instalment, days past due = max(0, Pakistan calendar date minus
  due date). An instalment due today has zero overdue days and a separate status.
- For a fully paid instalment, current days past due is zero. Settlement date
  and settlement lateness remain visible, using the last active allocated
  payment date. This retains late-payment evidence after settlement.
- Reporting is a current restated view using all recorded payment dates,
  including entries recorded later with an earlier payment date. It is not an
  event-time reconstruction of what was known historically.
- “Overdue” is a schedule calculation, not an SBP default/NPL classification or
  a prediction of default. These figures are only as reliable as the agreement
  and payment evidence entered by officers.

The existing monthly EWS and outcome-evidence inventory retain their existing
rules and reporting-month definitions. Calendar receipts are not silently
converted to those older monthly observations or to training labels. No live
bank, wallet or eCIB connector is introduced.

## Integrity and security

Every write rechecks the enabled actor's role inside the shared access-change
lock, then locks the facility and checks the current schedule and balances.
PostgreSQL concurrency tests cover competing schedule creation, duplicate
references and over-allocation. Manager access is required for contract versions
and voids; analysts can read and record payment evidence.

Schedule and receipt saves carry UUID intent keys. An unchanged retry recovers
the saved operation without another row or audit event. Reusing a key with
different content is a conflict. A stale expected schedule ID is refused. GET
is read-only. Financial screens reject mismatched case IDs and inconsistent
amounts; pending work is guarded on facility switches and page navigation.

Migration `0012_repayment_calendar` adds two tables and one migration audit
event; it does not backfill contracts, receipts or disbursement dates. The backup
restore verifier now compares both new tables, including voided records.

This is an evidence-recording and arithmetic feature, not independent bank
reconciliation, an accounting general ledger, an automated collections agent or
a validated lending model.
