# Sample files

`cashflow-intelligence-synthetic-36-months.csv` is a separate, deterministic
**synthetic** example for Cash-flow Intelligence (`/cashflow`). It contains
October 2023–September 2026 receipts and outflows, with seasonal variation and
a recent slowdown. Choose it in that workspace, or use **Load synthetic
example**. It is not real customer data and not a credit-model training set.
See [method and computed example results](../cashflow-intelligence-2026-10-28.md).

`sample-wallet-statement.csv` is a **synthetic** merchant wallet statement for
demos: a small trader, 28 March to 2 October 2026, generated with a fixed
random seed. It is not a real customer's data and not a real JazzCash or
Easypaisa export; real exports use their own column names, which the parser
matches from a list of common ones (see `backend/services/statement_service.py`).

On the Credit Scoring page, choose **Fill turnover from a statement** and pick
this file. The first and last months are partial and are left out, so the
figures come from the six full months April to September.

Every calendar month inside the statement period is included, even when it has
no transactions. Such a month contributes zero inflow, outflow and transactions
to the turnover and consistency calculations. Coverage is inferred from the
first and last readable, successful, non-zero transactions; verify that an
uploaded export contains the complete intervening period.

Unreadable amounts (including non-finite values) are left out and counted in
the summary's warnings. A malformed CSV or totals too large to calculate are
refused with a validation message.
