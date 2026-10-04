# Sample files

`sample-wallet-statement.csv` is a **synthetic** merchant wallet statement for
demos: a small trader, 28 March to 2 October 2026, generated with a fixed
random seed. It is not a real customer's data and not a real JazzCash or
Easypaisa export; real exports use their own column names, which the parser
matches from a list of common ones (see `backend/services/statement_service.py`).

On the Credit Scoring page, choose **Fill turnover from a statement** and pick
this file. The first and last months are partial and are left out, so the
figures come from the six full months April to September.
