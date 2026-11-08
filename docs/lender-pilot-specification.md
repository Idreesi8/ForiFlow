# ForiFlow lender pilot: draft specification and evidence contract

Status: a reviewable proposal, not an activated lending policy, regulatory
approval, production model, data-sharing agreement or live pilot. No lender
partner or lender outcome dataset is established by this document.

## Decisions required from the lender

| Decision | Required specification | Current state |
| --- | --- | --- |
| Intended population | SME segment, geography, eligibility and exclusions | Not agreed |
| Product | Working-capital/invoice/POS/etc.; repayment structure, fees and terms | Not agreed |
| Target | Exact event, threshold, cure/restructure/write-off handling and observation window | Not agreed |
| Decision use | Recommendation, limit, pricing or conditions; human authority and escalation | Existing app supports recommendations and human decisions; pilot mandate not agreed |
| Permitted data use | Collection/use authority, purpose, controller/processor roles, retention and withdrawal process | Source-reference register exists; lender legal/operational process not established |
| Pilot owners | Business, credit risk, data, compliance, security and independent validation | Not appointed |

For example, “ever reaches 90+ days past due within 12 months of disbursement”
is a possible research event/window pairing. It is **not selected** for
ForiFlow and is not a regulatory loan-classification rule. Contractual arrears,
research targets and regulatory classifications must remain distinct.

## Minimum evidence contract

1. **Identity/linkage:** stable pseudonymous borrower and facility identifiers.
   Repeated facilities must be linkable without exporting direct identifiers
   into modelling files. Do not infer identity from business names.
2. **Decision-time record:** application timestamp, product, requested amount,
   tenor, original features, feature-generation version, available-source
   cut-offs, model version, policy version and officer decision/override reason.
3. **Source authority and provenance:** permission/authority reference, terms,
   purposes and validity, source capture/event timestamps, document/version
   identifier, transformation history and review actor. The new case register
   is an after-assessment reference aid, not pre-ingestion enforcement.
4. **Contract:** recorded approval and actual disbursement dates, contractual
   due dates/amounts and documented changes. The current repayment calendar
   records officer assertions and explicit allocations, not bank reconciliation.
5. **Repayment events:** actual event and recording timestamps, stable receipt
   reference, amount in integer paisa, allocation, reversals/corrections and
   reconciliation state. Missing payments are unknown evidence until the
   source is reconciled; they cannot automatically become default labels.
6. **Outcome coverage:** observation start/end, event date and definition
   version, completeness, censoring, cures, restructures and write-offs. A
   “no default” label needs adequate follow-up, not simply no event on file.

Consent/authority for lending does not imply permission for research/training.
External source access, retention and transfers require the lender's approved
arrangements; no new connector or data-access right is created by this draft.

## Evaluation design before training

- Freeze the intended use, target/window and feature-availability cut-offs.
  Exclude information learned after the assessment from its predictor set.
- Design chronological evaluation around actual originations and mature
  outcomes. Keep repeat borrowers together where required by the intended
  test question; explicitly distinguish new-borrower generalisation from
  repeat-borrower monitoring. Do not silently discard overlaps to improve a
  reported score.
- Fit WOE/binning, imputers, clipping, feature selection, resampling and model
  tuning on training data only. Fit calibration on disjoint development data.
  Keep an untouched later-time evaluation sample.
- Compare a logistic baseline and a constrained tree model on the same
  protocol. Evaluate discrimination, precision-recall, calibration curves,
  uncertainty and lender-defined costs/capacity. AUC alone is insufficient.
- Set sample and event-count requirements from the desired precision,
  confidence intervals, model complexity and subgroup coverage. There is no
  universal “two years/thousands of loans” minimum that certifies readiness.
- Officer approvals/overrides are decisions, not repayment ground truth.
  Rejected applicants have unobserved loan outcomes in this book; do not
  label them good/bad or claim unbiased performance on all applicants.
- Evaluate applicable subgroup risks using lawfully available, controlled
  evaluation attributes. Excluding protected fields from model inputs does
  not establish fairness. Sparse groups remain inconclusive.

## Pilot release gates

1. **Data gate:** scope/target agreed; data-use arrangements approved;
   pre-ingestion controls implemented; sources reconciled; histories sufficiently
   mature and complete. The current app does not satisfy this gate by itself.
2. **Validation gate:** independent review of reproducibility, leakage,
   calibration, subgroup limitations, operating thresholds and documented
   acceptance/stop criteria. Current consumer-data benchmarks are not SME
   lending validation.
3. **Security/operations gate:** verified encryption and key management,
   least-privilege access, retention/deletion processes, incident response,
   restore/rollback and third-party review appropriate to deployment.
4. **Shadow gate:** capture predictions against the agreed prospective protocol
   without automated lending action; compare to reconciled later outcomes.
   Define monitoring owners, escalation, disabling and model-promotion authority.

These are completion criteria, not a calendar promise. Outcome maturation and
external reviews may dominate engineering time. FastAPI, React, PostgreSQL and
the existing model registry remain the current stack; additional orchestration,
identity or deployment platforms need a specific operational justification.
