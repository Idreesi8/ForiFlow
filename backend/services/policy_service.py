"""The credit policy engine: versioned cut-offs and authority limits.

Three layers, kept apart:

* ``scoring_service`` produces the model assessment (score, probability).
* this module turns an assessment into a **recommendation** under the active
  policy version, and says who may approve.
* ``decision_service`` records what an authorised officer decides.

A policy version's figures are never edited. A change is a new version, and
activating it retires the previous one. Every assessment stores the version it
was made under together with a snapshot of the rule that applied, so later
policy changes cannot alter what a past application was recommended.

The shipped policy is a demo policy: configurable, and not validated for
Pakistani SME lending.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import manager_approval_limit_pkr
from models.database import Application, CreditPolicy, User, utcnow
from schemas import RECOMMENDATION_OF, Decision, PolicyCreate, RiskBand
from services import audit_service, policy_rules
from services.audit_service import Action, AuditContext
from services.policy_rules import ScoreBands

_POLICY_FIELDS = (
    "version",
    "name",
    "status",
    "decline_max_score",
    "manual_review_max_score",
    "manager_approval_limit_pkr",
    "decline_override_admin_only",
)

_BAND_WORDS = {RiskBand.HIGH: "high", RiskBand.MEDIUM: "medium", RiskBand.LOW: "low"}


def policy_state(policy: CreditPolicy) -> dict:
    """A policy version as it is written to the audit trail."""
    return {name: getattr(policy, name) for name in _POLICY_FIELDS}


def bands_of(policy: CreditPolicy) -> ScoreBands:
    """The score cut-offs of a policy version."""
    return ScoreBands(
        decline_max_score=policy.decline_max_score,
        manual_review_max_score=policy.manual_review_max_score,
    )


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """What a policy version says about one assessment."""

    policy_id: int
    policy_version: str
    policy_name: str
    recommendation: Decision
    risk_band: RiskBand
    bands: ScoreBands
    triggered_rules: list[dict]
    approve_requires: str
    authority_reason: str
    manager_approval_limit_pkr: float
    decline_override_admin_only: bool
    reason: str

    def snapshot(self) -> dict:
        """The evaluation as stored with the application, for good."""
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_name": self.policy_name,
            "recommendation": RECOMMENDATION_OF[self.recommendation].value,
            "risk_band": self.risk_band.value,
            "bands": {
                "decline_max_score": self.bands.decline_max_score,
                "manual_review_max_score": self.bands.manual_review_max_score,
            },
            "triggered_rules": self.triggered_rules,
            # The inputs of the authority rule. Who may approve is worked out
            # from these, so it follows an escalation without rewriting this.
            "authority_rule": {
                "manager_approval_limit_pkr": self.manager_approval_limit_pkr,
                "decline_override_admin_only": self.decline_override_admin_only,
            },
            "authority_at_assessment": {
                "approve_requires": self.approve_requires,
                "reason": self.authority_reason,
            },
            "reason": self.reason,
        }


def evaluate(policy: CreditPolicy, risk_score: float, loan_amount_pkr: float) -> PolicyEvaluation:
    """Read a model score under a policy version. Pure: nothing is stored."""
    bands = bands_of(policy)
    recommendation = policy_rules.recommendation_for(risk_score, bands)
    risk_band = policy_rules.risk_band_for(risk_score, bands)
    rule = policy_rules.triggered_rule(risk_score, bands)
    role, authority_reason = policy_rules.approval_authority(
        loan_amount_pkr=loan_amount_pkr,
        recommendation=recommendation,
        manager_approval_limit_pkr=policy.manager_approval_limit_pkr,
        decline_override_admin_only=policy.decline_override_admin_only,
        escalated=False,
    )
    triggered = [rule]
    if authority_reason != "within_manager_limit":
        triggered.append(
            {
                "rule": authority_reason,
                "threshold": policy.manager_approval_limit_pkr,
                "loan_amount_pkr": loan_amount_pkr,
            }
        )
    label = RECOMMENDATION_OF[recommendation].value
    reason = (
        f"Recommendation: {label}. Score {risk_score:.2f} is {rule['comparison']} "
        f"{rule['threshold']:g}, which is {_BAND_WORDS[risk_band]} risk under "
        f"{policy.name} v{policy.version}. Approval needs "
        f"{'an admin' if role == 'admin' else 'a manager or admin'}; "
        "the decision is the officer's."
    )
    return PolicyEvaluation(
        policy_id=policy.id,
        policy_version=policy.version,
        policy_name=policy.name,
        recommendation=recommendation,
        risk_band=risk_band,
        bands=bands,
        triggered_rules=triggered,
        approve_requires=role,
        authority_reason=authority_reason,
        manager_approval_limit_pkr=policy.manager_approval_limit_pkr,
        decline_override_admin_only=policy.decline_override_admin_only,
        reason=reason,
    )


def _seed_demo_policy(db: Session) -> CreditPolicy:
    """Create and activate the demo policy in a database that has none.

    PostgreSQL gets it from migration 0007; this covers ``create_all`` schemas
    (SQLite: tests and the laptop fallback). The manager limit is taken once
    from ``MANAGER_APPROVAL_LIMIT_PKR``, where releases before 2.0 kept it.
    """
    now = utcnow()
    policy = CreditPolicy(
        version=policy_rules.DEMO_POLICY_VERSION,
        name=policy_rules.DEMO_POLICY_NAME,
        description=(
            "Default demo policy: the cut-offs ForiFlow has always used. "
            "Configurable; not validated for Pakistani SME lending."
        ),
        status="active",
        decline_max_score=policy_rules.DEMO_DECLINE_MAX_SCORE,
        manual_review_max_score=policy_rules.DEMO_MANUAL_REVIEW_MAX_SCORE,
        manager_approval_limit_pkr=manager_approval_limit_pkr(),
        decline_override_admin_only=True,
        created_by=audit_service.SYSTEM_ACTOR,
        activated_at=now,
        activated_by=audit_service.SYSTEM_ACTOR,
    )
    db.add(policy)
    db.flush()
    audit_service.record(
        db,
        action=Action.POLICY_CREATED,
        entity_type="credit_policy",
        entity_id=policy.id,
        new=policy_state(policy),
        details={"source": "seeded demo policy"},
    )
    audit_service.record(
        db,
        action=Action.POLICY_ACTIVATED,
        entity_type="credit_policy",
        entity_id=policy.id,
        previous={"active": None},
        new={"active": policy.version},
    )
    return policy


def active_policy(db: Session) -> CreditPolicy:
    """The policy version assessments are made under now. Does not commit."""
    policy = db.scalar(select(CreditPolicy).where(CreditPolicy.status == "active"))
    if policy is not None:
        return policy
    if db.scalar(select(func.count()).select_from(CreditPolicy)) == 0:
        try:
            with db.begin_nested():
                return _seed_demo_policy(db)
        except IntegrityError:  # another worker seeded it a moment earlier
            policy = db.scalar(select(CreditPolicy).where(CreditPolicy.status == "active"))
            if policy is not None:
                return policy
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No credit policy is active. An admin must activate a policy version.",
    )


def bands_for_application(db: Session, application: Application) -> ScoreBands:
    """The cut-offs an application was assessed under, else the active policy's."""
    stored = (application.policy_evaluation or {}).get("bands")
    if stored:
        return ScoreBands(
            decline_max_score=float(stored["decline_max_score"]),
            manual_review_max_score=float(stored["manual_review_max_score"]),
        )
    return bands_of(active_policy(db))


def get(db: Session, policy_id: int, *, for_update: bool = False) -> CreditPolicy:
    """A policy version by id, or ``404``."""
    policy = db.get(CreditPolicy, policy_id, with_for_update=for_update)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy version {policy_id} was not found.",
        )
    return policy


def create_version(
    db: Session, body: PolicyCreate, *, actor: User, context: AuditContext | None
) -> CreditPolicy:
    """Add a policy version as a draft. It changes nothing until activated."""
    active_policy(db)  # make sure the default exists before versions are added
    if db.scalar(select(CreditPolicy).where(CreditPolicy.version == body.version)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Policy version {body.version!r} already exists. A version is never "
                "edited; choose a new version number."
            ),
        )
    policy = CreditPolicy(
        version=body.version,
        name=body.name,
        description=body.description,
        status="draft",
        decline_max_score=body.decline_max_score,
        manual_review_max_score=body.manual_review_max_score,
        manager_approval_limit_pkr=body.manager_approval_limit_pkr,
        decline_override_admin_only=body.decline_override_admin_only,
        created_by=actor.username,
    )
    db.add(policy)
    db.flush()
    audit_service.record(
        db,
        action=Action.POLICY_CREATED,
        entity_type="credit_policy",
        entity_id=policy.id,
        actor=actor,
        new=policy_state(policy),
        details={"description": policy.description},
        context=context,
    )
    return policy


def activate(
    db: Session, policy: CreditPolicy, *, actor: User, context: AuditContext | None
) -> CreditPolicy:
    """Make ``policy`` the active version and retire the one it replaces.

    Applications already assessed keep the version and the rule snapshot they
    were assessed under. Only assessments made from now on use the new version.
    """
    if policy.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Policy version {policy.version} is already active.",
        )
    now = utcnow()
    current = db.scalar(
        select(CreditPolicy).where(CreditPolicy.status == "active").with_for_update()
    )
    if current is not None:
        current.status = "retired"
        current.retired_at = now
        # Flushed first: only one row may be active at any moment.
        db.flush()
        audit_service.record(
            db,
            action=Action.POLICY_RETIRED,
            entity_type="credit_policy",
            entity_id=current.id,
            actor=actor,
            previous={"status": "active"},
            new={"status": "retired", "replaced_by": policy.version},
            context=context,
        )
    previous_status = policy.status
    policy.status = "active"
    policy.activated_at = now
    policy.activated_by = actor.username
    policy.retired_at = None
    db.flush()
    audit_service.record(
        db,
        action=Action.POLICY_ACTIVATED,
        entity_type="credit_policy",
        entity_id=policy.id,
        actor=actor,
        previous={
            "status": previous_status,
            "active": current.version if current is not None else None,
        },
        new={**policy_state(policy), "active": policy.version},
        context=context,
    )
    return policy


def applications_assessed(db: Session) -> dict[int, int]:
    """How many applications each policy version has assessed."""
    return {
        policy_id: count
        for policy_id, count in db.execute(
            select(Application.policy_id, func.count())
            .where(Application.policy_id.is_not(None))
            .group_by(Application.policy_id)
        ).all()
    }
