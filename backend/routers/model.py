"""Model evaluation endpoints: how the served model performs, and against what."""

from __future__ import annotations

from typing import Annotated, Any
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.database import Application, ModelVersion, get_db
from diagnostic_schemas import CaseDiagnostics, ModelInputRequest, ModelInputReport
from schemas import ModelVersionResponse
from services.auth_service import get_current_user
from services import feature_contract
from services.drift_service import drift_report
from services.scoring_service import ScoringService, get_scoring_service
from services import applicability_service
from services.model_diagnostics import build_diagnostics
from services.input_checks import check_inputs
from operating_schemas import OperatingFigures, OperatingRequest, OperatingReport
from services.operating_checks import check_operating_figures
from services.statement_service import parse_statement, StatementError
from services.feature_study import StudySummary, load_study
from cashflow_schemas import CashflowRequest, CashflowReport
from services.cashflow_intelligence import analyse_csv as analyse_cashflow

router = APIRouter(
    prefix="/model",
    tags=["Model"],
    dependencies=[Depends(get_current_user)],
)


@router.post('/cashflow-intelligence', response_model=CashflowReport,
             summary='Local statement trend and chronologically tested receipt estimates')
def cashflow_intelligence(inputs: CashflowRequest, response: Response) -> CashflowReport:
    response.headers['Cache-Control'] = 'no-store'
    try:
        return analyse_cashflow(inputs.csv, inputs.date_order)
    except StatementError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get('/feature-study', response_model=StudySummary,
            summary='Measured train-only feature engineering research')
def feature_study(response: Response,
                  scorer: Annotated[ScoringService, Depends(get_scoring_service)]) -> StudySummary:
    response.headers['Cache-Control'] = 'no-store'
    try:
        return load_study(scorer)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='No completed feature study has been published.') from None
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise HTTPException(status_code=409, detail='Feature research could not be verified against the active credit model. Results are withheld.') from None


@router.post('/operating-checks', response_model=OperatingReport,
             summary='Use operating figures without scoring or saving an assessment')
def operating_checks(inputs: OperatingRequest, response: Response) -> OperatingReport:
    response.headers['Cache-Control'] = 'no-store'
    try:
        summary = parse_statement(inputs.statement_csv).as_dict() if inputs.statement_csv else None
    except StatementError as error:
        raise HTTPException(status_code=422, detail=f'Statement: {error}') from None
    figures = OperatingFigures(**inputs.model_dump(exclude={'statement_csv'}))
    return check_operating_figures(figures, summary)


@router.get('/applications/{application_id}/operating-checks', response_model=OperatingReport,
            summary='Calculate operating checks from the recorded case figures')
def saved_operating_checks(application_id: int, response: Response,
                           db: Annotated[Session, Depends(get_db)]) -> OperatingReport:
    response.headers['Cache-Control'] = 'no-store'
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail='The requested assessment was not found.')
    try:
        figures = OperatingFigures(**{name: getattr(application, name) for name in OperatingFigures.model_fields})
    except ValueError:
        raise HTTPException(status_code=409, detail='Recorded figures do not support these operating checks.') from None
    return check_operating_figures(figures, application.turnover_evidence, application_id)


@router.get('/sme-field-research', summary='Verified acquisition and fit of candidate SME datasets')
def sme_field_research() -> dict:
    path = Path(__file__).resolve().parents[1] / 'ml' / 'sme_field_research.json'
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail='SME dataset research has not been recorded.') from None


@router.get('/applicability', summary='The trained input-anomaly reference and its provenance')
def applicability_model(scorer: Annotated[ScoringService, Depends(get_scoring_service)]) -> dict:
    return applicability_service.summary(scorer)


@router.post('/input-checks', response_model=ModelInputReport,
             summary='Inspect five unsaved model inputs without creating a credit assessment')
def unsaved_input_checks(inputs: ModelInputRequest, response: Response,
                         scorer: Annotated[ScoringService, Depends(get_scoring_service)]) -> ModelInputReport:
    response.headers['Cache-Control'] = 'no-store'
    return check_inputs(inputs, scorer)


@router.get('/applications/{application_id}/diagnostics', response_model=CaseDiagnostics,
            summary='Read-only, source-verified ensemble and sensitivity checks for a saved case')
def application_diagnostics(application_id: int, db: Annotated[Session, Depends(get_db)],
                            scorer: Annotated[ScoringService, Depends(get_scoring_service)]) -> CaseDiagnostics:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail='The requested assessment was not found.')
    return build_diagnostics(db, application, scorer)


def _require(payload: dict[str, Any] | None, command: str) -> dict[str, Any]:
    """Return the recorded results or a ``404`` naming the script that makes them."""
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Not recorded yet. Run `python -m ml.{command}` in the backend.",
        )
    return payload


@router.get(
    "/versions",
    response_model=list[ModelVersionResponse],
    summary="Every model that has scored here, and which is active",
)
async def model_versions(db: Annotated[Session, Depends(get_db)]) -> list[ModelVersionResponse]:
    """Model records, newest first, with how many applications each scored.

    A model is recorded the first time it scores against this database, with a
    SHA-256 of its artefact files. ``engine`` is ``ml`` for the trained
    ensemble and ``surrogate`` for the hand-weighted fallback formula; a
    surrogate row carries the reason it was serving. Applications scored before
    this record existed keep the version string they stored and are not counted
    against a row.
    """
    counts = dict(
        db.execute(
            select(Application.model_version_id, func.count())
            .where(Application.model_version_id.is_not(None))
            .group_by(Application.model_version_id)
        ).all()
    )
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc())).all()
    return [
        ModelVersionResponse.model_validate(row).model_copy(
            update={"applications_scored": int(counts.get(row.id, 0))}
        )
        for row in rows
    ]


@router.get(
    "/versions/active",
    response_model=ModelVersionResponse,
    summary="The model scoring right now",
)
async def active_model_version(db: Annotated[Session, Depends(get_db)]) -> ModelVersionResponse:
    """The active model record; ``404`` before anything has been scored or registered."""
    row = db.scalar(select(ModelVersion).where(ModelVersion.status == "active"))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No model has been registered yet. It is recorded at startup or first score.",
        )
    count = db.scalar(
        select(func.count()).select_from(Application).where(Application.model_version_id == row.id)
    )
    return ModelVersionResponse.model_validate(row).model_copy(
        update={"applications_scored": int(count or 0)}
    )


@router.get("/evaluation", summary="Final test-set evaluation of the served model")
async def model_evaluation() -> dict[str, Any]:
    """ROC curve, class-wise results, calibration and default rate per band.

    Measured once by ``ml.evaluate_model`` on the final test set (20% of the
    file) that neither the model, its preprocessing nor its calibrator has
    seen. ``holdout`` is the pre-2.2 name for the same figures. The score
    cut-offs used here are model evaluation cut-offs, not the credit policy in
    force. These figures describe a demonstration model on public consumer
    credit data; they are not live portfolio results.
    """
    from ml.features import load_model_evaluation

    return _require(load_model_evaluation(), "evaluate_model")


@router.get("/early-warning", summary="The fitted early-warning Markov chain")
async def early_warning_model() -> dict[str, Any]:
    """Transition matrix, outlook per state, hold-out check and alternatives.

    Fitted by ``ml.ews_markov`` on the UCI credit card file: monthly repayment
    histories of consumer card accounts in Taiwan, not SME loans.
    """
    from ml.features import load_ews_transition

    return _require(load_ews_transition(), "ews_markov")


@router.get("/drift", summary="Live applications against the training population")
async def population_drift(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Population Stability Index of the score and of each model input.

    Compares every stored application with the distributions recorded by
    ``ml.evaluate_model``. Inputs are rebuilt exactly as scoring builds them
    (same turnover estimate, clip bounds and repayment-history reading). The
    reference is the public training file, so a shift here is expected for a
    real Pakistani portfolio; it says the model needs re-validating, not that
    the applicants are worse.
    """
    from ml.features import (
        apply_clips,
        build_raw_features,
        load_feature_metadata,
        load_model_evaluation,
        payment_history_levels,
        snap_payment_history,
    )

    evaluation = _require(load_model_evaluation(), "evaluate_model")
    reference = evaluation.get("reference_distributions")
    reference = {
        name: {key: value for key, value in row.items() if key != "source"}
        for name, row in (reference or {}).items()
    }
    if not reference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reference distributions. Re-run `python -m ml.evaluate_model`.",
        )
    metadata = load_feature_metadata()
    clips = metadata.get("feature_clips", {})
    levels = payment_history_levels(metadata)

    live: dict[str, list[float]] = {name: [] for name in reference}
    for application in db.scalars(select(Application)):
        raw = build_raw_features(application)
        clipped = apply_clips(raw, clips)
        if levels is not None:
            clipped["payment_history_score"] = snap_payment_history(
                raw["payment_history_score"], levels
            )
        for name in reference:
            live[name].append(
                float(application.risk_score) if name == "risk_score" else clipped[name]
            )
    report = drift_report(reference, live)
    report["reference_label"] = "Reference / Demo Distribution"
    report["reference_note"] = (
        "The reference is the public consumer credit training file (training inputs, "
        "validation scores), not a bank portfolio. This is not production drift "
        "monitoring: that needs a reference from the bank's own approved loans."
    )
    return report


@router.get("/fairness", summary="Subgroup Performance Analysis on the final test set")
async def fairness_audit() -> dict[str, Any]:
    """Per group: count, default rate, AUC, precision and recall where the sample allows.

    Recorded once by ``ml.evaluate_model`` on the final test set for age,
    income, housing and loan purpose: attributes of the public file that the
    model never reads. Small groups are marked "Insufficient sample size". The
    file has no gender, region or religion. Descriptive only: it does not
    establish that the model is fair.
    """
    from ml.features import load_fairness_audit

    return _require(load_fairness_audit(), "fairness_audit")


@router.get("/comparison", summary="Served ensemble against the baselines")
async def model_comparison() -> dict[str, Any]:
    """Logistic regression, XGBoost alone, random forest alone and the ensemble.

    Same split and train-only preprocessing for each: 5-fold CV on the training
    split and validation figures (``ml.train_real_model``), final-test figures
    once (``ml.evaluate_model``). A paired t-test over the CV folds compares each
    with the ensemble.
    """
    from ml.features import load_model_comparison

    return _require(load_model_comparison(), "compare_models")


LIMITATIONS: list[str] = [
    "Demonstration model trained on public consumer credit data. It is not validated "
    "for Pakistani SME lending and must not be used for autonomous credit decisions.",
    "Three features only (facility size against turnover, repayment history read as "
    "clean or adverse, years in operation); other intake fields do not change the score.",
    "Monthly turnover is estimated from digital receipts or cash flow typed by an "
    "officer; there is no bank, bureau or POS integration.",
    "The calibrated probability is display only and calibrated to the public file's "
    "default rate, not to any Pakistani SME portfolio.",
    "EWS monitoring data in a pilot is officer-entered or demo data.",
    "Drift is measured against the public training file (a reference / demo "
    "distribution), not against a bank portfolio.",
]


@router.get("/card", summary="Model status, performance, data and limits in one place")
async def model_card(
    scorer: Annotated[ScoringService, Depends(get_scoring_service)],
) -> dict[str, Any]:
    """What the Model page shows first. Every figure comes from the recorded files.

    ``serving_engine`` is the engine scoring right now; the trained model's
    figures are reported whether or not it is the one serving, and say so.
    """
    from ml.data_quality import load_data_quality
    from ml.features import load_feature_metadata, load_model_comparison, load_model_evaluation

    try:
        metadata = load_feature_metadata()
    except (OSError, ValueError):
        metadata = {}
    evaluation = load_model_evaluation() or {}
    if evaluation.get("model_trained_at") != metadata.get("trained_at"):
        evaluation = {}
    quality = load_data_quality() or {}
    comparison = load_model_comparison() or {}
    final = evaluation.get("final_test") or {}
    calibration = metadata.get("calibration") or {}
    return {
        "serving_engine": scorer.engine,
        "serving_model_version": scorer.model_version,
        "serving_artifact_sha256": scorer.artifact_sha256,
        "serving_fallback_reason": scorer.fallback_reason,
        "status": {
            "model_version": (
                f"ensemble-xgb-rf-{metadata.get('dataset', 'unknown')}-{metadata.get('trained_at', 'undated')}"
                if metadata
                else None
            ),
            "trained_at": metadata.get("trained_at"),
            "training_protocol_version": metadata.get("training_protocol_version"),
            "dataset_identifier": metadata.get("dataset_identifier") or metadata.get("dataset"),
            "dataset_type": metadata.get("dataset_type_label")
            or "Public consumer credit data, not Pakistani SME banking data",
            "dataset_sha256": metadata.get("dataset_sha256"),
            "random_seed": metadata.get("random_seed"),
            "split": metadata.get("split"),
            "features": metadata.get("feature_names"),
            "preprocessing": metadata.get("preprocessing"),
        },
        "performance": {
            "evaluated_on": "final test set (measured once)" if final else None,
            "final_test_raw": final.get("metrics_raw"),
            "final_test_calibrated": final.get("metrics_calibrated"),
            "cross_validation_training_split": metadata.get("cross_validation"),
            "validation": (metadata.get("validation") or {}).get("ensemble_raw"),
            "previous_model": metadata.get("previous_model"),
        },
        "evaluation_thresholds": evaluation.get("evaluation_thresholds")
        or metadata.get("evaluation_threshold"),
        "policy_note": (
            "Credit policy thresholds (Approve / Manual Review / Decline) are configured "
            "on the Credit Policy page and stored with each application. They are not "
            "derived from, or optimised on, these model results."
        ),
        "baselines": evaluation.get("baselines"),
        "baseline_cross_validation": {
            name: {
                key: row.get(key)
                for key in ("auc_roc_mean", "auc_roc_std", "pr_auc_mean", "f1_mean", "brier_mean", "vs_served")
            }
            for name, row in (comparison.get("models") or {}).items()
        }
        if comparison.get("model_trained_at") == metadata.get("trained_at")
        else None,
        "calibration": {
            "method": calibration.get("method_label"),
            "fitted_on": calibration.get("fitted_on"),
            "selection": calibration.get("selection"),
            "display_only": True,
            "brier_raw_final_test": (final.get("raw") or {}).get("brier"),
            "brier_calibrated_final_test": (final.get("calibrated") or {}).get("brier"),
            "brier_no_skill_final_test": final.get("brier_no_skill"),
            "ece_raw_final_test": (final.get("raw") or {}).get("expected_calibration_error"),
            "ece_calibrated_final_test": (final.get("calibrated") or {}).get("expected_calibration_error"),
            "note": calibration.get("note"),
        }
        if calibration
        else None,
        "shap": {
            "output_space": metadata.get("shap_output_space"),
            "additivity_max_error": metadata.get("shap_additivity_max_error"),
            "reference": metadata.get("shap_reference"),
        },
        "data_quality": {
            "rows_in_file": quality.get("rows"),
            "columns_in_file": quality.get("columns"),
            "model_features": quality.get("feature_count"),
            "target_positive_rate": (quality.get("target") or {}).get("positive_rate"),
            "duplicate_rows": quality.get("duplicate_rows"),
            "excluded_rows": quality.get("excluded_rows"),
            "missing_values": quality.get("missing_values"),
            "model_feature_missing_values": quality.get("model_feature_missing_values"),
            "dataset_type": quality.get("dataset_type"),
        }
        if quality
        else None,
        "limitations": LIMITATIONS,
        "model_card": "docs/model_card.md",
    }


@router.get("/data-quality", summary="Data-quality report of the training file")
async def data_quality() -> dict[str, Any]:
    """Rows, target balance, missing, duplicate and out-of-range values, and what
    training does about them. Public consumer credit data, not SME banking data."""
    from ml.data_quality import load_data_quality

    return _require(load_data_quality(), "data_quality")


@router.get("/feature-contract", summary="Which intake fields reach the score")
async def model_feature_contract(
    scorer: Annotated[ScoringService, Depends(get_scoring_service)],
) -> dict[str, Any]:
    """Model features, fields collected but unused, and future SME data needs."""
    return feature_contract.contract(scorer)
