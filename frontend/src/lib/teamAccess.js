export const TEAM_ROLES = [
  { value: 'analyst', label: 'Analyst', can: 'Scores applications, records monthly monitoring and takes alerts for review.' },
  { value: 'manager', label: 'Manager', can: 'Everything an analyst can, plus approving within the policy limit, rejecting or escalating applications and resolving alerts.' },
  { value: 'admin', label: 'Admin', can: 'Everything a manager can, plus restricted approvals, escalated decisions, credit policy, audit access and officer account management.' },
];
export const roleLabel = role => TEAM_ROLES.find(item => item.value === role)?.label ?? role;

export function filterTeam(users, { search = '', role = 'all', status = 'all' } = {}) {
  const query = search.trim().toLocaleLowerCase();
  return users.filter(user => (!query || user.username.toLocaleLowerCase().includes(query))
    && (role === 'all' || user.role === role)
    && (status === 'all' || (user.is_active !== false ? 'enabled' : 'disabled') === status));
}

export function teamChangeBlock(user, actor, mode) {
  if (!actor?.is_active || actor.role !== 'admin') return 'Your current account cannot manage access. An enabled admin must make this change.';
  if (!user) return 'This account is no longer available. Refresh the list.';
  if (mode !== 'history' && user.id === actor.id) return mode === 'role'
    ? 'You cannot change your own role. Ask another enabled admin.'
    : 'You cannot disable your own account.';
  return null;
}
