"""Smoke-test the trained model end to end with a single sample applicant.

Run from the ``backend`` directory::

    python -m ml.predict_sample

Loads the persisted artefacts through the same :class:`MLScoringService` the API
uses, scores one applicant, and prints the mapped features, decision, confidence
and SHAP breakdown. Also checks that base value plus contributions reconstructs
the score, and reports latency, since every ``POST /score`` pays this cost.
"""

from __future__ import annotations

import sys
import time

from schemas import SMEApplicant
from services.scoring_service import MLScoringService

# A mid-market Faisalabad textile SME: solid repayment record, moderate leverage.
SAMPLE = {
    "applicant_name": "Ayesha Siddiqui",
    "business_name": "Siddiqui Textiles (Faisalabad)",
    "loan_amount_pkr": 2_500_000,
    "tenure_months": 24,
    "monthly_digital_payments": 1_450_000,
    "payment_history_score": 78,
    "inventory_turnover": 6.5,
    "order_consistency": 82,
    "existing_debt_pkr": 900_000,
    "cash_flow_proxy": 410_000,
    "years_in_operation": 7,
    "num_employees": 18,
}


def main() -> int:
    """Score the sample applicant and print a full diagnostic report."""
    from ml.features import artifacts_available

    if not artifacts_available():
        print(
            "Model artefacts are missing. Train them first:\n"
            "    python -m ml.train_real_model",
            file=sys.stderr,
        )
        return 1

    load_started = time.perf_counter()
    service = MLScoringService.from_artifacts()
    load_seconds = time.perf_counter() - load_started

    metadata = service.metadata
    cross_validation = metadata.get("cross_validation", {})

    print("=" * 74)
    print("FORIFLOW MODEL — SAMPLE PREDICTION")
    print("=" * 74)
    print(f"Model version   : {service.model_version}")
    print(f"Trained on      : {metadata.get('dataset')} ({metadata.get('rows', 0):,} rows)")
    print(
        f"Cross-validated : AUC-ROC {cross_validation.get('auc_roc_mean', float('nan')):.4f} "
        f"| F1 {cross_validation.get('f1_mean', float('nan')):.4f}"
    )
    print(f"Features        : {', '.join(service.feature_names)}")
    print(f"SHAP space      : {service.output_space}")
    print(f"Artefact load   : {load_seconds * 1000:.0f} ms")

    applicant = SMEApplicant(**SAMPLE)
    print(f"\nApplicant: {applicant.applicant_name} — {applicant.business_name}")
    print(f"  Facility  PKR {applicant.loan_amount_pkr:,.0f} over {applicant.tenure_months} months")
    print(f"  Cash flow PKR {applicant.cash_flow_proxy:,.0f} / month")
    print(f"  Existing debt PKR {applicant.existing_debt_pkr:,.0f}")

    score_started = time.perf_counter()
    result = service.score(applicant)
    score_seconds = time.perf_counter() - score_started

    print("\nMapped model features (after clipping to trained range):")
    for name in service.feature_names:
        raw = result.raw_features.get(name, float("nan"))
        used = result.normalised_features.get(name, float("nan"))
        lower, upper = service.feature_clips[name]
        flag = "  <- clipped" if not lower <= raw <= upper else ""
        print(
            f"  {name:<24} raw {raw:>10.4f}   used {used:>10.4f}"
            f"   trained range [{lower:.3f}, {upper:.3f}]{flag}"
        )

    print("\nDecision")
    print(f"  Risk score  : {result.risk_score:.2f} / 100")
    print(f"  Decision    : {result.decision.value}")
    print(f"  Risk band   : {result.risk_band.value}")
    print(f"  Confidence  : {result.confidence:.1f} / 100")
    print(f"  Model PD    : {result.probability_of_default:.4f} (balanced-prior)")
    print(f"  Latency     : {score_seconds * 1000:.0f} ms")

    contributions = service.explain(result)
    print("\nSHAP contributions (score points)")
    print(f"  {'feature':<26}{'value':>12}{'points':>10}{'share':>9}")
    for contribution in contributions:
        print(
            f"  {contribution.label[:25]:<26}{contribution.value:>12.4f}"
            f"{contribution.contribution:>+10.2f}{contribution.weight:>9.1%}"
        )

    total = sum(contribution.contribution for contribution in contributions)
    reconstructed = service.base_value + total
    print(f"\n  base value {service.base_value:.2f} + contributions {total:+.2f} "
          f"= {reconstructed:.2f} (score {result.risk_score:.2f})")
    additive = abs(reconstructed - result.risk_score) <= 0.15
    print(f"  additivity: {'OK' if additive else 'MISMATCH'} "
          f"(delta {abs(reconstructed - result.risk_score):.4f})")

    explanation = service.build_explanation(
        result, application_id=0, business_name=applicant.business_name
    )
    print(f"\nNarrative: {explanation.narrative}")
    print(f"Compliance: {explanation.compliance_note}")

    return 0 if additive else 1


if __name__ == "__main__":
    sys.exit(main())
