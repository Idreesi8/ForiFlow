import { bandIndexForScore } from './policyBands.js';

export const POLICY_TERMS = ['decline_max_score', 'manual_review_max_score', 'manager_approval_limit_pkr', 'decline_override_admin_only'];

export function validPolicyTerms(policy) {
  return policy && POLICY_TERMS.slice(0, 3).every(key => typeof policy[key] === 'number' && Number.isFinite(policy[key])) &&
    policy.decline_max_score >= 0 && policy.decline_max_score < policy.manual_review_max_score && policy.manual_review_max_score <= 100 &&
    policy.manager_approval_limit_pkr >= 0 && policy.manager_approval_limit_pkr <= 500_000_000 && typeof policy.decline_override_admin_only === 'boolean';
}

export function checkedPolicyVersions(versions) {
  if (!Array.isArray(versions) || !versions.length || versions.some(policy => !validPolicyTerms(policy) ||
    !Number.isSafeInteger(policy.id) || policy.id < 1 || typeof policy.version !== 'string' || !policy.version.trim() ||
    typeof policy.name !== 'string' || !policy.name.trim() || !['draft', 'active', 'retired'].includes(policy.status) ||
    policy.is_active !== (policy.status === 'active') || !Number.isSafeInteger(policy.applications_assessed) || policy.applications_assessed < 0) ||
    new Set(versions.map(policy => policy.id)).size !== versions.length ||
    new Set(versions.map(policy => policy.version)).size !== versions.length || versions.filter(policy => policy.is_active).length !== 1) {
    throw Object.assign(new Error('The policy versions could not be verified. Refresh before comparing or changing policy.'), { code:'INVALID_POLICY_DETAILS' });
  }
  return versions;
}

export function policyDraftFrom(active) {
  if (!validPolicyTerms(active)) throw new Error('Current policy terms are unavailable.');
  return { version: '', name: '', description: '', decline_max_score: String(active.decline_max_score),
    manual_review_max_score: String(active.manual_review_max_score), manager_approval_limit_pkr: String(active.manager_approval_limit_pkr),
    decline_override_admin_only: active.decline_override_admin_only };
}

export function preparePolicyDraft(form) {
  const version = String(form.version ?? '').trim(), name = String(form.name ?? '').trim();
  const description = String(form.description ?? '').trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/.test(version)) throw new Error('Use a 1–32 character version with letters, digits, dots, hyphens or underscores.');
  if (name.length < 3 || name.length > 120) throw new Error('Enter a policy name of 3–120 characters.');
  if (description.length > 2000) throw new Error('Keep the policy description within 2,000 characters.');
  const numbers = Object.fromEntries(POLICY_TERMS.slice(0, 3).map(key => [key,
    typeof form[key] === 'string' && form[key].trim() !== '' ? Number(form[key]) : NaN]));
  const payload = { version, name, description: description || null, ...numbers, decline_override_admin_only: form.decline_override_admin_only };
  if (!validPolicyTerms(payload)) throw new Error('Use finite cut-offs with 0 ≤ Decline < Manual Review ≤ 100, and a manager limit from PKR 0 to 500,000,000.');
  return payload;
}

export function policyReviewBlock(candidate, versions, actor) {
  if (!actor || typeof actor.username !== 'string' || !actor.username.trim() || !['analyst', 'manager', 'admin'].includes(actor.role)) return 'Your current officer account could not be verified.';
  if (candidate.mode !== 'compare' && actor.role !== 'admin') return 'Only an enabled admin can create or activate a policy. Your current account does not have that authority.';
  if (candidate.mode === 'create') return versions.some(policy => policy.version === candidate.policy.version) ? 'This version is already on file. Inspect it before choosing another version; a version cannot be overwritten.' : null;
  const target = versions.find(policy => policy.id === candidate.policy.id);
  if (!target) return 'This policy version is no longer available. Refresh the versions.';
  if (candidate.mode === 'activate' && target.is_active) return 'This version is already active. No activation is needed.';
  return null;
}

/** Illustration only: uses the same band boundaries as the existing dial. */
export function illustratedRecommendation(score, policy) {
  if (typeof score !== 'string' || !score.trim() || !validPolicyTerms(policy)) return null;
  const value = Number(score);
  if (!Number.isFinite(value) || value < 0 || value > 100) return null;
  return ['Recommend Decline', 'Recommend Manual Review', 'Recommend Approve'][bandIndexForScore(value, policy)];
}
