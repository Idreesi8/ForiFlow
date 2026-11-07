# Banking AI research: verified findings and ForiFlow implementation

Reviewed 8 November 2026. External references are research inputs, not evidence
that ForiFlow is validated for production lending.

## Source checks

| Reference | What was verified | Use in ForiFlow |
| --- | --- | --- |
| [KPMG, AI in Banking Sector (2026)](https://assets.kpmg.com/content/dam/kpmgsites/sg/pdf/2026/05/ai-in-banking-sector-2026.pdf.coredownload.inline.pdf) | Discusses supervised agentic workflows and lifecycle governance. An industry report, not a model benchmark. | Prioritise traceable evidence and human control before adding autonomous execution. |
| [Kuanova and Otegen, Artificial Intelligence in Banking Risk Management: A Bibliometric Analysis](https://www.mdpi.com/2227-7072/14/4/93) | Published 3 April 2026; reviews 83 papers from 2020–2024. The supplied URL was for a different paper. | Useful research map; does not establish any ForiFlow performance claim. |
| [Artificial Intelligence in Banking: A Bibliometric Analysis of Research Trends, Intellectual Structure, and Performance-Related Themes](https://www.mdpi.com/1911-8074/19/8/581) | Published 3 August 2026. This is the title attached to the URL supplied for two different titles. | Do not cite this as the competitive-dynamics meta-analysis; the original title/source pairing is incorrect. |
| [Meta-Analysis of Artificial Intelligence's Influence on Competitive Dynamics for Small- and Medium-Sized Financial Institutions](https://www.mdpi.com/2813-2203/4/3/24) | Located the correct publisher record (Analytics 4(3), 24). Describes literature review, sentiment bibliometrics and network analysis. | Useful for institution-size and integration strategy; not a comparison of credit-model predictive accuracy. |
| [Cavdar and Bozanta, AI-based credit card fraud detection: a machine learning approach with model explainability on real-world data](https://link.springer.com/article/10.1007/s10115-026-02773-7) | Published 20 May 2026. Compares nine models and sampling strategies; includes SHAP, LIME and DeepLIFT. Random Forest was robust, tuned XGBoost achieved superior F1, and TabTransformer led the deep-learning comparisons. | Evaluate algorithms against the actual task and held-out data; a newer architecture is not automatically a better credit model. |
| [Cambridge CCAF, 2026 Global AI in Financial Services Report](https://www.jbs.cam.ac.uk/faculty-research/centres/alternative-finance/publications/2026-global-ai-in-financial-services-report/) | The report and its agentic-AI adoption findings exist. Findings describe surveyed organisations, not all banks or ForiFlow. | Supports researching supervised internal review workflows; does not validate autonomous approval. |
| [Evident, supplied 2026 index page](https://evidentinsights.com/insights/banks-ai-index-2026-report) and [DRUID banking use cases](https://www.druidai.com/blog/7-use-cases-for-agentic-ai-in-banking) | The pages resolve. The latter is vendor material. | Context and ideas; not independent evidence of model accuracy, legal compliance or expected productivity gains. |

The quoted “more than 60% of financial AI projects fail because of bad data”
statistic has not been established from a primary McKinsey publication here.
Do not repeat it as a verified fact. Likewise, the blanket claim that every
bank must use SHAP or LIME is not a verified regulatory requirement.

## Dataset fit

- [Feedzai BAF](https://github.com/feedzai/bank-account-fraud) is a generated,
  privacy-preserving account-opening **fraud** benchmark derived from anonymised
  real data. Temporal dynamics and class imbalance are explicit concerns.
- [ULB/Kaggle credit-card fraud](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud)
  targets card transaction fraud. Its anonymised features cannot be mapped to
  ForiFlow's SME repayment features merely because both concern banking.
- [PaySim's original project](https://github.com/EdgarLopezPhD/PaySim) generates
  synthetic mobile-money transactions for fraud research. It is not a history
  of observed Pakistani SME defaults.

These datasets can support a **separate fraud research track**, with their
licences, provenance, time splits and decision-time feature availability checked
before use. They cannot supply default labels for existing ForiFlow facilities.
No dataset was downloaded, substituted into the credit model or used to claim
new SME accuracy in this change.

## Implemented: historical explanation integrity

The explanation endpoint previously regenerated missing/unreadable explanations
with the serving model. Explicit refresh also used the serving model, even if
it differed from the original. For missing policy snapshots the helper could
fall back to the active policy. That could present an explanation unrelated to
the assessment an officer was reviewing, despite preserving the old database
score.

Regeneration now requires:

1. A linked original model record whose version, engine and artifact fingerprint
   match both the application and serving model. Matching version names alone
   do not suffice.
2. Valid thresholds from the assessment's saved policy snapshot. Today's active
   policy is never substituted for regeneration.
3. Reproduction of the saved score within 0.011 points, the original
   recommendation and recorded risk band, plus finite additive attributions
   consistent with the score within accumulated hundredth-point rounding.

Failure returns HTTP 409 with a readable reason before writing an explanation
or audit event. Existing readable saved explanations remain accessible after
model retirement. GET remains read-only. Successful POST recovery stores an
explanation only under the original verified model and records the existing
audit event. Refresh never overwrites a readable saved explanation.

This changes the API's refresh contract: using refresh to obtain a different
model's assessment is no longer supported. A separate, explicitly labelled
comparison workflow would be needed for that purpose.

Regression tests cover changed version/engine/fingerprint, missing provenance,
missing/invalid/nonfinite policy thresholds, changed score/band/recommendation,
unreadable caches, nonfinite or inconsistent attributions, read-only recovery,
and recovery with the actual trained ensemble. Failed requests are checked
against snapshots of every test database table.

This guard concerns regeneration. It does not cryptographically authenticate
old cached explanations or replace the existing model diagnostics and audit
controls.

## Next engineering priorities

1. A supervised, read-only case-review agent with narrowly scoped tools and
   field-level evidence references. It should abstain on missing evidence,
   resist instructions inside uploaded documents, and never decide credit or
   change policy. Evaluate tool selection, case isolation, unsupported claims,
   abstention and failure recovery before activation. No new agent is claimed
   by this change.
2. Event-driven monitoring requires an authenticated transaction source,
   event-time ordering, duplicate handling, corrections/replay, freshness
   indicators and measured latency. Current periodic EWS records should not
   be advertised as a live banking feed.
3. Credit-model advancement requires dated, lender-defined outcomes and enough
   mature facilities, with borrower-disjoint chronological evaluation,
   calibration and business-cost metrics. The existing outcome-evidence
   inventory remains a collection aid, not a training-ready dataset.

No provider, external account, new dependency, model artifact, database schema,
real case decision or active policy was changed for this implementation.
