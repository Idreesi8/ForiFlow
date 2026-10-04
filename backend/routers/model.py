"""Model evaluation endpoints: how the served model performs, and against what."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from services.auth_service import get_current_user

router = APIRouter(
    prefix="/model",
    tags=["Model"],
    dependencies=[Depends(get_current_user)],
)


def _require(payload: dict[str, Any] | None, command: str) -> dict[str, Any]:
    """Return the recorded results or a ``404`` naming the script that makes them."""
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Not recorded yet. Run `python -m ml.{command}` in the backend.",
        )
    return payload


@router.get("/evaluation", summary="Hold-out evaluation of the served model")
async def model_evaluation() -> dict[str, Any]:
    """ROC curve, class-wise results, calibration and default rate per band.

    Measured by ``ml.evaluate_model`` on the 20% hold-out that neither the
    served model nor its calibrator has seen. These figures describe the trained
    ensemble on the public training file; they are not live portfolio results.
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


@router.get("/comparison", summary="Served model against the alternatives")
async def model_comparison() -> dict[str, Any]:
    """Cross-validated metrics of every model the ensemble was chosen over.

    Recorded by ``ml.compare_models`` with the same data, folds and pipeline
    for each model, including a paired t-test against the served ensemble.
    """
    from ml.features import load_model_comparison

    return _require(load_model_comparison(), "compare_models")
