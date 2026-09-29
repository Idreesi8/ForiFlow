-- What ForiFlow stores, and where. Run with show-data.bat (Windows) or:
--   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < scripts/show-data.sql
-- Read-only: every statement is a SELECT or a psql listing.

\pset pager off
\echo
\echo '=== Tables in the ForiFlow database (schema owned by Alembic) ==='
\dt

\echo '=== Schema version applied by Alembic ==='
SELECT version_num FROM alembic_version;

\echo '=== Row counts ==='
SELECT 'applications' AS table_name, count(*) AS rows FROM applications
UNION ALL SELECT 'ews_tracking', count(*) FROM ews_tracking
UNION ALL SELECT 'alerts', count(*) FROM alerts
UNION ALL SELECT 'users', count(*) FROM users;

\echo '=== Latest scored applications ==='
SELECT id, business_name, loan_amount_pkr, risk_score, decision AS model_decision,
       CASE WHEN decision <> 'Manual Review' THEN decision
            ELSE coalesce(review_decision, 'Pending review') END AS final_decision,
       scored_by, reviewed_by,
       to_char(created_at, 'YYYY-MM-DD HH24:MI') AS scored_at
FROM applications
ORDER BY id DESC
LIMIT 5;

\echo '=== Officer decisions on Manual Review cases (with the reason) ==='
SELECT id, business_name, review_decision, reviewed_by,
       to_char(reviewed_at, 'YYYY-MM-DD HH24:MI') AS reviewed_at, review_note
FROM applications
WHERE review_decision IS NOT NULL
ORDER BY reviewed_at DESC
LIMIT 5;

\echo '=== The SHAP explanation stored with the latest application (audit trail) ==='
SELECT e ->> 'business_name' AS business,
       (e ->> 'base_value')::numeric AS base_value,
       c ->> 'label' AS input,
       round((c ->> 'contribution')::numeric, 2) AS points,
       (e ->> 'risk_score')::numeric AS score
FROM (
  SELECT shap_explanation_json::jsonb AS e
  FROM applications
  WHERE shap_explanation_json IS NOT NULL
  ORDER BY id DESC
  LIMIT 1
) latest,
LATERAL jsonb_array_elements(e -> 'feature_contributions') AS c;

\echo '=== Model that produced it ==='
SELECT shap_explanation_json::jsonb ->> 'model_version' AS model_version
FROM applications
WHERE shap_explanation_json IS NOT NULL
ORDER BY id DESC
LIMIT 1;

\echo '=== Latest EWS monthly observations ==='
SELECT id, borrower_id, month_number, installment_status, bureau_balance,
       pos_cash_balance, monthly_score
FROM ews_tracking
ORDER BY id DESC
LIMIT 5;

\echo '=== Latest EWS alerts ==='
SELECT id, borrower_id, baseline_score, current_score, score_drop,
       estimated_days_to_default, alert_status, assigned_to, resolved_by, resolution_note
FROM alerts
ORDER BY id DESC
LIMIT 5;

\echo '=== Officer accounts: passwords are bcrypt hashes, never plain text ==='
SELECT id, username, role, left(hashed_password, 7) || '... (' || length(hashed_password) || ' chars)' AS password_hash
FROM users
ORDER BY id;
