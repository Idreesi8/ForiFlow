# ForiFlow risk register

What can go wrong when a bank relies on ForiFlow, what the prototype does
about it today, and what a bank would still have to add. Likelihood and impact
are our own judgement for a single-branch pilot, not measured frequencies.

Scale: **L** low, **M** medium, **H** high.

## Model risk

| # | Risk | Likelihood | Impact | In ForiFlow today | Still needed in a bank |
|---|------|:---:|:---:|---|---|
| M1 | **Wrong population.** The model is trained on a public consumer-loan file mapped onto SMEs, not on Pakistani SME loans. Its ranking may not carry over. | H | H | Stated in every explanation's compliance note and on the Model Performance page. Manual Review (41–70) keeps a person on 63% of hold-out cases. | Retrain and re-validate on the bank's own SME book before any automatic approval. |
| M2 | **Probability of default is calibrated to the wrong base rate.** It reflects the file's 21.8% default rate. | H | M | The score and bands use the raw ranking, not the PD. The PD is labelled as calibrated to the public file. A calibrator from another training run is ignored at start-up. | Refit the calibrator on the bank's default rate and monitor it every quarter. |
| M3 | **Only 3 features drive the score** (facility size against turnover, repayment history, years in operation). Two businesses that differ in every other intake field score the same. | H | M | Unused fields are marked on the form and named in the compliance note. | Bank data with more features; the same pipeline reached AUC 0.8656 on a richer public file. |
| M4 | **Sharp cliff at 30% facility-to-turnover.** A small change in the loan amount moves the score by about 28 points (PKR 540,000 scores 55.74, PKR 547,920 scores 27.97 for the same business). | M | M | The form warns before submission. Path to approval tells the officer the exact amount on each side of the cliff. Monotone constraints guarantee the score never rises with a larger loan. | Review the cliff against the bank's own data; smooth it if the bank's defaults do not show it. |
| M5 | **Repayment history is read as only clean or adverse** (snapped at 52.5), because the training data holds a yes/no bureau flag. | H | M | Documented on the form and in the compliance note. | A real bureau score with a graded scale. |
| M6 | **Data drift.** Applicants change over time and the model is not retrained. | M | M | The Model Performance page reports the Population Stability Index of the score and of each model input against the training data, with the value chance alone would give, and withholds a verdict below 100 applications. Model version and training date are stored with every explanation. | A retraining trigger tied to the PSI, and tracking of the realised default rate per band. |
| M7 | **Explanations trusted more than they deserve.** SHAP explains the model, not the real cause of default. | M | M | SHAP is exact for this model and additive (checked in tests). Feature correlations are low (largest Spearman 0.055 on the training part), so attribution is not split between related inputs. | Faithfulness tests reported with each model release. |

## Data and input risk

| # | Risk | Likelihood | Impact | In ForiFlow today | Still needed in a bank |
|---|------|:---:|:---:|---|---|
| D1 | **Officer types a wrong figure**, or a figure that favours the applicant. Payment history is typed in; turnover is typed unless a statement is attached. | H | H | Turnover can be filled from a statement CSV; the API re-reads the file and records on the credit file whether the scored figures match it. Range checks on every field. Each assessment records who scored it. | A direct feed from the wallet provider or bank, so the statement itself cannot be edited before upload; a second officer check above a set amount. |
| D2 | **No live ECIB feed.** Bureau balance and payment history are typed. | H | M | Said on the form, the sidebar and the compliance note. | An eCIB or private-bureau integration. |
| D3 | **Early-warning inputs depend on someone recording the month.** A facility nobody monitors raises no alert. | H | H | The Loan book shows how many approved facilities have monthly records, and how many months lack an amount paid. | Feed repayment data from the core banking system. |
| D4 | **The early-warning chain is fitted on the wrong population**: consumer card accounts in Taiwan in 2005, not Pakistani SME term loans. It also under-predicts for accounts already 60-89 days late (31% predicted, 53% actual on 34 hold-out accounts), and hazard models with more inputs rank accounts better (AUC 0.92 against 0.86). | H | M | Stated on the Model Performance page and beside every monitoring result. The score-drop rule still alerts on bureau and POS signals. Only the latest month drives an alert; corrections are handled consistently. | Refit the chain, or a hazard model, on the bank's own monthly repayment records. |

## Decision and process risk

| # | Risk | Likelihood | Impact | In ForiFlow today | Still needed in a bank |
|---|------|:---:|:---:|---|---|
| P1 | **Automation bias.** An officer approves because the score says so. | M | H | Manual Review needs an admin, a written reason of at least 10 characters, and cannot be changed afterwards. Model band and officer decision are stored side by side. | Sampling of approved cases by credit audit. |
| P2 | **Unfair outcomes for a group.** The public data has no gender or region, so fairness across them cannot be measured. | M | H | Age is deliberately not a feature. Business sector is collected for reporting and is not read by the model. | A fairness review on bank data that carries the protected attributes. |
| P3 | **Path to approval read as an offer**, or used to coach an applicant to restate turnover. | M | M | The panel says it is not an offer and that turnover must be evidenced. | A policy on who may see it. |
| P4 | **Not SBP-certified.** Explanations are built to support an adverse-action file, not approved by the regulator. | H | H | Stated in the API description, the sidebar and every compliance note. | Regulatory review before production use. |

## Security and operations risk

| # | Risk | Likelihood | Impact | In ForiFlow today | Still needed in a bank |
|---|------|:---:|:---:|---|---|
| S1 | **A stolen login token works until it expires** (up to 8 hours); it cannot be revoked. | L | H | Bound to 127.0.0.1; bcrypt cost 12; passwords of 12 characters or more; role read from the database on every request. | Short-lived tokens with refresh, or the bank's single sign-on. |
| S2 | **One machine, one process.** A laptop failure stops scoring and can lose data. | M | H | PostgreSQL data sits on a named Docker volume; `show-data.bat` reads it back. | Backups, a server deployment and several API workers. |
| S3 | **Roles do not match the bank's credit authority limits.** Three roles exist (analyst, manager, admin), but a manager can approve a facility of any size. | M | M | Manager-only and admin-only actions are enforced by the API (403), not just hidden on screen. | Approval limits by amount and a second approver above a threshold. |
| S4 | **A tampered model file would change every score.** | L | H | Artefacts are baked into the image; the model version is stored with each explanation. | Signed artefacts and a controlled release process. |
