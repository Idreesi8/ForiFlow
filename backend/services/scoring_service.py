"""Credit scoring and explainability business logic for ForiFlow.

Two engines share one interface, so routers and schemas are identical either way:

:class:`MLScoringService`
    Serves the trained XGBoost + RandomForest soft-voting ensemble produced by
    ``ml/train_real_model.py``, with genuine TreeSHAP explanations. Selected
    automatically whenever the model artefacts are present on disk.

:class:`ScoringService`
    A deterministic linear surrogate used as the fallback when no artefacts have
    been trained yet. Every feature is normalised to ``[0, 1]`` where ``1`` is
    the lowest-risk end of the observed SME range, and the score is the weighted
    sum scaled to ``0-100`` (higher is better). Because the surrogate is
    additive, exact SHAP values follow analytically: each contribution is the
    feature's weighted deviation from a neutral applicant, so contributions plus
    the base value reproduce the score.

Set ``FORIFLOW_SCORING_ENGINE`` to ``ml``, ``surrogate`` or ``auto`` (default) to
override the choice; ``ml`` fails loudly if the artefacts cannot be loaded.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from schemas import Decision, ExplanationResponse, RiskBand, ShapFeatureContribution

logger = logging.getLogger(__name__)


@runtime_checkable
class SMEApplicantLike(Protocol):
    """Attributes the scorer reads from an applicant.

    Any object exposing these fields can be scored: the incoming
    :class:`schemas.SMEApplicant` payload or a persisted
    :class:`models.database.Application` row.
    """

    loan_amount_pkr: float
    tenure_months: int
    monthly_digital_payments: float
    payment_history_score: float
    inventory_turnover: float
    order_consistency: float
    existing_debt_pkr: float
    cash_flow_proxy: float
    years_in_operation: float
    num_employees: int

# Weights sum to 1.0. Ordering reflects the relative importance agreed with the
# credit policy team for thin-file Pakistani SMEs.
FEATURE_WEIGHTS: dict[str, float] = {
    "payment_history_score": 0.22,
    "loan_affordability": 0.18,
    "debt_burden": 0.15,
    "monthly_digital_payments": 0.14,
    "order_consistency": 0.11,
    "inventory_turnover": 0.08,
    "years_in_operation": 0.07,
    "num_employees": 0.05,
}

FEATURE_LABELS: dict[str, str] = {
    "payment_history_score": "Repayment history (officer-entered)",
    "loan_affordability": "Installment affordability vs cash flow",
    "debt_burden": "Existing debt burden",
    "monthly_digital_payments": "Monthly digital payment volume",
    "order_consistency": "Order consistency",
    "inventory_turnover": "Inventory turnover",
    "years_in_operation": "Years in operation",
    "num_employees": "Business size (employees)",
}

# Normalisation bounds, calibrated on the SME reference portfolio. Monthly
# digital receipts below the floor carry no signal for a formal facility.
DIGITAL_PAYMENTS_FLOOR_PKR: float = 50_000.0
DIGITAL_PAYMENTS_CAP_PKR: float = 5_000_000.0
INVENTORY_TURNOVER_CAP: float = 12.0
YEARS_IN_OPERATION_CAP: float = 10.0
EMPLOYEES_CAP: int = 50

# Decision policy: 0-40 Rejected, 41-70 Manual Review, 71-100 Approved.
REJECT_UPPER_BOUND: float = 40.0
MANUAL_REVIEW_UPPER_BOUND: float = 70.0

# A neutral applicant sits at the midpoint of every normalised feature, which
# makes the SHAP base value exactly 50 points.
NEUTRAL_NORMALISED_VALUE: float = 0.5
BASE_VALUE: float = 50.0

COMPLIANCE_NOTE: str = (
    "SHAP values are stored on-premise so a bank can support an SBP-oriented "
    "adverse-action file. Payment-history and bureau-balance fields are "
    "officer-entered; there is no live ECIB or other bureau connector. "
    "All amounts are in PKR. ForiFlow is not SBP-certified."
)


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    """Clamp ``value`` into the inclusive ``[lower, upper]`` interval."""
    return max(lower, min(upper, value))


def _log_scaled(value: float, floor: float, cap: float) -> float:
    """Scale a heavy-tailed monetary amount into ``[0, 1]``.

    A log transform keeps large-turnover SMEs from dominating the linear model
    while still rewarding order-of-magnitude differences in volume. The floor
    anchors the scale so that negligible amounts score 0 instead of inheriting
    the log curve's steep lower tail.
    """
    if value <= floor or cap <= floor:
        return 0.0
    span = math.log1p(cap) - math.log1p(floor)
    return clamp((math.log1p(value) - math.log1p(floor)) / span)


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Model output for a single applicant.

    The trailing fields are only populated by :class:`MLScoringService`: the
    surrogate has no probability estimate and derives its contributions on
    demand instead of caching them.
    """

    risk_score: float
    decision: Decision
    risk_band: RiskBand
    normalised_features: dict[str, float] = field(default_factory=dict)
    raw_features: dict[str, float] = field(default_factory=dict)
    probability_of_default: float | None = None
    confidence: float | None = None
    contributions: dict[str, float] | None = None


class ScoringService:
    """Stateless credit scoring engine backed by the linear surrogate.

    Injected into routers via :func:`get_scoring_service` so that tests (or the
    ML-backed subclass) can substitute their own instance.
    """

    model_version: str = "surrogate-linear-v1"

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        base_value: float = BASE_VALUE,
    ) -> None:
        """Store the weight vector, normalising it so that weights sum to 1."""
        raw_weights = dict(FEATURE_WEIGHTS if weights is None else weights)
        if not raw_weights:
            raise ValueError("At least one feature weight is required.")
        total = sum(raw_weights.values())
        if total <= 0:
            raise ValueError("Feature weights must sum to a positive value.")
        self.weights: dict[str, float] = {k: v / total for k, v in raw_weights.items()}
        self.base_value = base_value
        self.compliance_note = COMPLIANCE_NOTE

    def normalise_features(self, applicant: SMEApplicantLike) -> dict[str, float]:
        """Map raw applicant features onto the ``[0, 1]`` risk-adjusted scale.

        ``1.0`` always means "best observed behaviour" so that every weight can
        stay positive and the resulting explanation is easy to read.
        """
        monthly_installment = applicant.loan_amount_pkr / max(applicant.tenure_months, 1)
        cash_flow = applicant.cash_flow_proxy

        if cash_flow <= 0:
            # No verifiable cash flow: affordability and debt capacity are the
            # worst possible, regardless of the requested amount.
            affordability = 0.0
            debt_burden = 0.0
        else:
            affordability = clamp(1.0 - (monthly_installment / cash_flow))
            annual_cash_flow = cash_flow * 12.0
            debt_burden = clamp(1.0 - (applicant.existing_debt_pkr / annual_cash_flow))

        return {
            "payment_history_score": clamp(applicant.payment_history_score / 100.0),
            "loan_affordability": affordability,
            "debt_burden": debt_burden,
            "monthly_digital_payments": _log_scaled(
                applicant.monthly_digital_payments,
                DIGITAL_PAYMENTS_FLOOR_PKR,
                DIGITAL_PAYMENTS_CAP_PKR,
            ),
            "order_consistency": clamp(applicant.order_consistency / 100.0),
            "inventory_turnover": clamp(
                applicant.inventory_turnover / INVENTORY_TURNOVER_CAP
            ),
            "years_in_operation": clamp(
                applicant.years_in_operation / YEARS_IN_OPERATION_CAP
            ),
            "num_employees": clamp(applicant.num_employees / EMPLOYEES_CAP),
        }

    @staticmethod
    def decision_for(risk_score: float) -> Decision:
        """Apply the ForiFlow decision policy to a score."""
        if risk_score <= REJECT_UPPER_BOUND:
            return Decision.REJECTED
        if risk_score <= MANUAL_REVIEW_UPPER_BOUND:
            return Decision.MANUAL_REVIEW
        return Decision.APPROVED

    @staticmethod
    def risk_band_for(risk_score: float) -> RiskBand:
        """Map a score onto its reporting risk band."""
        if risk_score <= REJECT_UPPER_BOUND:
            return RiskBand.HIGH
        if risk_score <= MANUAL_REVIEW_UPPER_BOUND:
            return RiskBand.MEDIUM
        return RiskBand.LOW

    def score(self, applicant: SMEApplicantLike) -> ScoreResult:
        """Score an applicant and derive its decision band.

        Returns a score in ``[0, 100]`` where higher is more creditworthy.
        """
        normalised = self.normalise_features(applicant)
        weighted_sum = sum(
            self.weights[feature] * value
            for feature, value in normalised.items()
            if feature in self.weights
        )
        risk_score = round(clamp(weighted_sum * 100.0, 0.0, 100.0), 2)

        return ScoreResult(
            risk_score=risk_score,
            decision=self.decision_for(risk_score),
            risk_band=self.risk_band_for(risk_score),
            normalised_features=normalised,
            raw_features=self._raw_feature_values(applicant),
        )

    @staticmethod
    def _raw_feature_values(applicant: SMEApplicantLike) -> dict[str, float]:
        """Collect the raw values displayed next to each contribution."""
        monthly_installment = applicant.loan_amount_pkr / max(applicant.tenure_months, 1)
        cash_flow = applicant.cash_flow_proxy
        return {
            "payment_history_score": float(applicant.payment_history_score),
            # Shown as an affordability ratio because the underlying feature is
            # engineered rather than submitted directly.
            "loan_affordability": round(
                monthly_installment / cash_flow if cash_flow > 0 else 0.0, 4
            ),
            "debt_burden": round(
                applicant.existing_debt_pkr / (cash_flow * 12.0) if cash_flow > 0 else 0.0,
                4,
            ),
            "monthly_digital_payments": float(applicant.monthly_digital_payments),
            "order_consistency": float(applicant.order_consistency),
            "inventory_turnover": float(applicant.inventory_turnover),
            "years_in_operation": float(applicant.years_in_operation),
            "num_employees": float(applicant.num_employees),
        }

    def explain(self, result: ScoreResult) -> list[ShapFeatureContribution]:
        """Derive additive SHAP-style contributions for a scored applicant.

        For a linear model the exact Shapley value of a feature is its weighted
        deviation from the neutral baseline, so ``sum(contributions) +
        base_value`` reconstructs the score. Contributions are returned sorted
        by absolute impact, which is the order the React waterfall chart uses.
        """
        contributions: list[ShapFeatureContribution] = []
        for feature, normalised in result.normalised_features.items():
            weight = self.weights.get(feature)
            if weight is None:
                continue
            impact = round(
                weight * 100.0 * (normalised - NEUTRAL_NORMALISED_VALUE), 2
            )
            contributions.append(
                ShapFeatureContribution(
                    feature=feature,
                    label=FEATURE_LABELS.get(feature, feature.replace("_", " ").title()),
                    value=result.raw_features.get(feature, normalised),
                    contribution=impact,
                    direction="increases" if impact >= 0 else "decreases",
                    weight=round(weight, 4),
                )
            )

        contributions.sort(key=lambda item: abs(item.contribution), reverse=True)
        return contributions

    def narrative(
        self, result: ScoreResult, contributions: list[ShapFeatureContribution]
    ) -> str:
        """Compose an adverse-action style summary for the credit file."""
        drivers = [c for c in contributions if c.contribution < 0][:3]
        strengths = [c for c in contributions if c.contribution > 0][:3]

        sentences = [
            f"Score {result.risk_score:.1f}/100 ({result.risk_band.value}) "
            f"resulted in a '{result.decision.value}' outcome."
        ]
        if strengths:
            sentences.append(
                "Supporting factors: "
                + ", ".join(f"{c.label.lower()} (+{c.contribution:.1f})" for c in strengths)
                + "."
            )
        if drivers:
            sentences.append(
                "Main concerns: "
                + ", ".join(f"{c.label.lower()} ({c.contribution:.1f})" for c in drivers)
                + "."
            )
        if result.decision is Decision.MANUAL_REVIEW:
            sentences.append(
                "Referred to a credit officer for manual verification of cash flow evidence."
            )
        return " ".join(sentences)


    def build_explanation(
        self, result: ScoreResult, application_id: int, business_name: str
    ) -> ExplanationResponse:
        """Assemble the full explanation payload for a scored application."""
        contributions = self.explain(result)
        return ExplanationResponse(
            application_id=application_id,
            business_name=business_name,
            risk_score=result.risk_score,
            decision=result.decision,
            risk_band=result.risk_band,
            base_value=self.base_value,
            feature_contributions=contributions,
            top_positive_factors=[
                c.label for c in contributions if c.contribution > 0
            ][:3],
            top_negative_factors=[
                c.label for c in contributions if c.contribution < 0
            ][:3],
            narrative=self.narrative(result, contributions),
            compliance_note=self.compliance_note,
            model_version=self.model_version,
        )


# Which trained feature, if any, carries each intake field into the model. Fields
# mapped to ``None`` have no counterpart in the public training data, so the
# ensemble cannot use them and the compliance note has to say so.
INTAKE_TO_ML_FEATURE: dict[str, str | None] = {
    "payment_history_score": "payment_history_score",
    "loan_affordability": "installment_to_income",
    "debt_burden": "debt_service_to_income",
    "years_in_operation": "years_in_operation",
    # Digital receipts estimate gross turnover, the denominator of loan_to_income.
    "monthly_digital_payments": "loan_to_income",
    "order_consistency": None,
    "inventory_turnover": None,
    "num_employees": None,
}

# Confidence blends how far the score sits from a decision boundary with how
# closely the two ensemble members agree.
CONFIDENCE_AGREEMENT_WEIGHT: float = 0.6
CONFIDENCE_MARGIN_WEIGHT: float = 0.4
CONFIDENCE_MARGIN_SPAN: float = 30.0
CONFIDENCE_DISAGREEMENT_SPAN: float = 0.5


class MLScoringService(ScoringService):
    """Scores applicants with the trained ensemble and real TreeSHAP values.

    Subclasses the surrogate so routers keep their ``ScoringService`` dependency
    and inherit the decision policy, narrative builder and explanation assembly
    unchanged. Only :meth:`score` and :meth:`explain` are model specific.

    The score is ``100 * (1 - PD)``. Because the ensemble is trained on
    SMOTE-balanced data its probabilities are calibrated to a 50% prior rather
    than the portfolio's true default rate, so the score is a *relative*
    creditworthiness ranking on a 0-100 scale, not an absolute default
    probability. That is also what keeps the base value near 50 and the policy
    bands meaningful.
    """

    def __init__(
        self,
        model: Any,
        scaler: Any,
        shap_bundle: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        """Wire up a loaded model, scaler and SHAP bundle."""
        super().__init__()
        self.model = model
        self.scaler = scaler
        self.metadata = metadata
        self.feature_names: list[str] = list(metadata["feature_names"])
        self.feature_clips: dict[str, list[float]] = metadata.get("feature_clips", {})
        self.explainers: dict[str, Any] = shap_bundle["explainers"]
        self.shap_weights: dict[str, float] = shap_bundle["weights"]
        self.output_space: str = shap_bundle.get("output_space", "probability")
        self.member_names: list[str] = [name for name, _ in model.estimators]
        self._tune_for_single_row_inference()
        self.base_value = self._expected_score()
        self.model_version = (
            f"ensemble-xgb-rf-{metadata.get('dataset', 'unknown')}-"
            f"{metadata.get('trained_at', 'undated')}"
        )
        self.compliance_note = self._compliance_note()

    # -- loading ----------------------------------------------------------

    @classmethod
    def from_artifacts(cls) -> MLScoringService:
        """Load the persisted artefacts from ``backend/ml``.

        Raises whatever the underlying loader raises; callers decide whether to
        fall back to the surrogate.
        """
        import joblib

        from ml.features import (
            MODEL_PATH,
            SCALER_PATH,
            SHAP_EXPLAINER_PATH,
            load_feature_metadata,
        )

        return cls(
            model=joblib.load(MODEL_PATH),
            scaler=joblib.load(SCALER_PATH),
            shap_bundle=joblib.load(SHAP_EXPLAINER_PATH),
            metadata=load_feature_metadata(),
        )

    def _tune_for_single_row_inference(self) -> None:
        """Force serial prediction on the loaded members.

        The forest is trained with ``n_jobs=-1``, but scoring one applicant at a
        time spends far more on thread dispatch than it saves: measured at 183 ms
        per call parallel versus a few milliseconds serial.
        """
        for estimator in self.model.estimators_:
            if hasattr(estimator, "n_jobs"):
                estimator.n_jobs = 1

    def _expected_score(self) -> float:
        """Score of an average training applicant, used as the SHAP base value."""
        from ml.shap_utils import expected_positive_value

        if self.output_space != "probability":
            # Log-odds contributions are rescaled onto the score gap, so the
            # portfolio's own default rate is the natural anchor.
            default_rate = float(self.metadata.get("default_rate", 0.5))
            return round(100.0 * (1.0 - default_rate), 2)

        expected_pd = sum(
            self.shap_weights[name] * expected_positive_value(explainer)
            for name, explainer in self.explainers.items()
        )
        return round(100.0 * (1.0 - expected_pd), 2)

    def _compliance_note(self) -> str:
        """Compliance footer naming the model and any unscored intake fields."""
        unused = [
            FEATURE_LABELS[intake_field]
            for intake_field, ml_feature in INTAKE_TO_ML_FEATURE.items()
            if ml_feature is None or ml_feature not in self.feature_names
        ]
        note = (
            f"{COMPLIANCE_NOTE} Scored by the trained XGBoost + RandomForest "
            f"ensemble ({self.metadata.get('dataset', 'unknown')} dataset, "
            f"AUC-ROC "
            f"{self.metadata.get('cross_validation', {}).get('auc_roc_mean', float('nan')):.3f}) "
            f"with TreeSHAP attributions."
        )
        if unused:
            note += (
                " Collected but not used by this model version: "
                + ", ".join(sorted(unused))
                + "."
            )
        return note

    # -- scoring ----------------------------------------------------------

    def _feature_frame(self, applicant: SMEApplicantLike):
        """Build the scaled model input plus the clipped and raw feature values."""
        import numpy as np

        from ml.features import apply_clips, build_raw_features

        raw = build_raw_features(applicant)
        clipped = apply_clips(raw, self.feature_clips)
        vector = np.array([[clipped[name] for name in self.feature_names]], dtype=float)
        return self.scaler.transform(vector), clipped, raw

    def score(self, applicant: SMEApplicantLike) -> ScoreResult:
        """Score an applicant with the trained ensemble.

        Returns a score in ``[0, 100]`` where higher is more creditworthy, along
        with the model's probability of default, a confidence heuristic and the
        SHAP contributions already expressed in score points.
        """
        scaled, clipped, raw = self._feature_frame(applicant)

        member_pds = self._member_probabilities(scaled)
        probability_of_default = self._ensemble_probability(member_pds)
        risk_score = round(clamp(100.0 * (1.0 - probability_of_default), 0.0, 100.0), 2)
        contributions = self._shap_contributions(scaled, risk_score)

        return ScoreResult(
            risk_score=risk_score,
            decision=self.decision_for(risk_score),
            risk_band=self.risk_band_for(risk_score),
            normalised_features=clipped,
            raw_features={name: round(value, 4) for name, value in raw.items()},
            probability_of_default=round(probability_of_default, 6),
            confidence=self._confidence(member_pds, risk_score),
            contributions=contributions,
        )

    def _member_probabilities(self, scaled) -> dict[str, float]:
        """Default probability from each ensemble member, keyed by name."""
        return {
            name: float(estimator.predict_proba(scaled)[0, 1])
            for name, estimator in zip(
                self.member_names, self.model.estimators_, strict=True
            )
        }

    def _ensemble_probability(self, member_pds: dict[str, float]) -> float:
        """Combine member probabilities exactly as soft voting does.

        Recomputed from the member predictions that :meth:`_confidence` needs
        anyway, which avoids a third pass over 250 trees per request. Equivalence
        with ``model.predict_proba`` is asserted in ``tests/test_ml_model.py``.
        """
        total_weight = sum(self.shap_weights[name] for name in member_pds)
        return sum(
            self.shap_weights[name] * probability
            for name, probability in member_pds.items()
        ) / total_weight

    def _shap_contributions(self, scaled, risk_score: float) -> dict[str, float]:
        """Attribute the score to each feature, in score points.

        Shapley values are additive across a weighted average of models, so
        averaging the members' attributions with the voting weights explains the
        ensemble's averaged probability exactly. Probabilities are negated and
        scaled by 100 because a higher default probability means a lower score.
        """
        import numpy as np

        from ml.shap_utils import positive_class_shap

        total = np.zeros(len(self.feature_names))
        for name, explainer in self.explainers.items():
            values = positive_class_shap(explainer.shap_values(scaled))[0]
            total += self.shap_weights[name] * np.asarray(values, dtype=float)

        if self.output_space == "probability":
            points = -100.0 * total
        else:
            points = self._rescale_log_odds(-total, risk_score)

        return {
            name: round(float(value), 2)
            for name, value in zip(self.feature_names, points, strict=True)
        }

    def _rescale_log_odds(self, signed, risk_score: float):
        """Project log-odds attributions onto the score gap they explain.

        Used only when the installed ``shap`` cannot build probability-space
        explainers. Signs and relative magnitudes are preserved exactly; the
        absolute point values are approximate because log-odds are not additive
        in score space.
        """
        import numpy as np

        signed = np.asarray(signed, dtype=float)
        gap = risk_score - self.base_value
        total = float(signed.sum())
        if abs(total) < 1e-9:
            return np.zeros_like(signed)
        return signed * (gap / total)

    def _confidence(self, member_pds: dict[str, float], risk_score: float) -> float:
        """Heuristic 0-100 confidence in the decision.

        Combines agreement between the two ensemble members with the score's
        distance from the nearest policy boundary. This is a decision-stability
        indicator for the credit officer, not a statistical confidence interval.
        """
        probabilities = list(member_pds.values())
        disagreement = max(probabilities) - min(probabilities)
        agreement = clamp(1.0 - disagreement / CONFIDENCE_DISAGREEMENT_SPAN)

        distance = min(
            abs(risk_score - REJECT_UPPER_BOUND),
            abs(risk_score - MANUAL_REVIEW_UPPER_BOUND),
        )
        margin = clamp(distance / CONFIDENCE_MARGIN_SPAN)

        confidence = (
            CONFIDENCE_AGREEMENT_WEIGHT * agreement + CONFIDENCE_MARGIN_WEIGHT * margin
        )
        return round(confidence * 100.0, 1)

    # -- explaining -------------------------------------------------------

    def explain(self, result: ScoreResult) -> list[ShapFeatureContribution]:
        """Render the cached SHAP contributions for the waterfall chart.

        ``weight`` reports each feature's share of the total absolute attribution
        for *this* applicant, which is the model-agnostic equivalent of the
        surrogate's fixed policy weights.
        """
        from ml.features import FEATURE_LABELS as ML_FEATURE_LABELS

        contributions = result.contributions or {}
        magnitude = sum(abs(value) for value in contributions.values()) or 1.0

        rendered = [
            ShapFeatureContribution(
                feature=name,
                label=ML_FEATURE_LABELS.get(name, name.replace("_", " ").title()),
                value=result.raw_features.get(name, 0.0),
                contribution=impact,
                direction="increases" if impact >= 0 else "decreases",
                weight=round(abs(impact) / magnitude, 4),
            )
            for name, impact in contributions.items()
        ]
        rendered.sort(key=lambda item: abs(item.contribution), reverse=True)
        return rendered


def _requested_engine() -> str:
    """Read the engine override, defaulting to automatic selection."""
    return os.getenv("FORIFLOW_SCORING_ENGINE", "auto").strip().lower()


@lru_cache(maxsize=1)
def get_scoring_service() -> ScoringService:
    """FastAPI dependency returning the shared, stateless scoring engine.

    Prefers the trained ensemble and falls back to the linear surrogate when its
    artefacts are absent, so the API still boots on a fresh checkout.
    """
    from ml.features import artifacts_available

    engine = _requested_engine()
    if engine == "surrogate":
        logger.info("Scoring engine pinned to the linear surrogate.")
        return ScoringService()

    if engine != "ml" and not artifacts_available():
        logger.warning(
            "No trained model artefacts found in backend/ml; falling back to the "
            "linear surrogate. Run 'python -m ml.train_real_model' to train one."
        )
        return ScoringService()

    try:
        service = MLScoringService.from_artifacts()
    except Exception:
        if engine == "ml":
            raise
        logger.exception("Failed to load model artefacts; using the linear surrogate.")
        return ScoringService()

    logger.info("Scoring engine: %s", service.model_version)
    return service
