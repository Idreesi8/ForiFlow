export const PRIORITIES = {
  urgent: { label: "Urgent", style: "bg-rose-50 text-rose-800 ring-rose-200" },
  attention: { label: "Needs attention", style: "bg-amber-50 text-amber-800 ring-amber-200" },
  routine: { label: "Routine", style: "bg-slate-100 text-slate-700 ring-slate-200" },
};

export const KINDS = { alert: "EWS follow-up", review: "Credit review", monitoring: "Monitoring record" };
export const ROLE_LABELS = {
  admin: "Admin decision required", manager_or_admin: "Manager or admin action", any_officer: "Any officer can record the month",
};

export const DESK_PAGE_SIZE = 25;

/** Keep only bounded worklist controls in navigation, never task records. */
export function readDeskQuery(value = "") {
  const params = value instanceof URLSearchParams ? value : new URLSearchParams(value);
  const rawPage = params.get("page") ?? "1";
  const page = /^[1-9]\d*$/.test(rawPage) && Number(rawPage) <= 20_000_001 ? Number(rawPage) : 1;
  return {
    kind: Object.hasOwn(KINDS, params.get("kind")) ? params.get("kind") : "",
    priority: Object.hasOwn(PRIORITIES, params.get("priority")) ? params.get("priority") : "",
    actionableOnly: params.get("actionable_only") === "true",
    search: (params.get("search") ?? "").slice(0, 100).trim(),
    page,
  };
}

export function deskQuery(view = {}) {
  const params = new URLSearchParams();
  if (view.kind) params.set("kind", view.kind);
  if (view.priority) params.set("priority", view.priority);
  if (view.actionableOnly === true) params.set("actionable_only", "true");
  if (view.search) params.set("search", view.search);
  if (view.page != null) params.set("page", String(view.page));
  const valid = readDeskQuery(params);
  const query = new URLSearchParams();
  if (valid.kind) query.set("kind", valid.kind);
  if (valid.priority) query.set("priority", valid.priority);
  if (valid.actionableOnly) query.set("actionable_only", "true");
  if (valid.search) query.set("search", valid.search);
  if (valid.page > 1) query.set("page", String(valid.page));
  return query.toString();
}

export function updateDeskQuery(current, changes) {
  return new URLSearchParams(deskQuery({ ...readDeskQuery(current), page: 1, ...changes }));
}

export function deskPath(view = {}) {
  const query = deskQuery(view);
  return `/action-desk${query ? `?${query}` : ""}`;
}

export function worklistReturnState(state) {
  const query = state?.worklistSearch;
  if (typeof query !== "string" || query.length > 2000) return undefined;
  return { worklistSearch: deskQuery(readDeskQuery(query)) };
}

export function worklistReturnPath(state) {
  const valid = worklistReturnState(state);
  return valid ? `/action-desk${valid.worklistSearch ? `?${valid.worklistSearch}` : ""}` : null;
}

export function positiveInteger(value) {
  if (!/^[1-9]\d*$/.test(String(value))) return null;
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : null;
}

export function taskPath(task) {
  const id = positiveInteger(task.application_id);
  if (!id) return "/action-desk";
  if (task.kind === "review") return `/shap/${id}`;
  const month = positiveInteger(task.first_missing_month);
  return `/alerts?facility=${id}${task.kind === "monitoring" && month ? `&month=${month}` : ""}#${task.kind === "monitoring" ? "monitoring" : "alert-queue"}`;
}

export function snapshotLabel(value) {
  return new Intl.DateTimeFormat("en-PK", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Karachi",
  }).format(new Date(value)) + " PKT";
}

export function briefingText(snapshot) {
  const first = snapshot.items.length ? snapshot.offset + 1 : 0;
  return [
    `ForiFlow officer briefing · ${snapshotLabel(snapshot.as_of)}`,
    `${snapshot.total_tasks} tasks across ${snapshot.application_count} cases in the complete portfolio.`,
    `This view: items ${first}–${snapshot.offset + snapshot.items.length} of ${snapshot.matching_tasks} matching tasks.`,
    ...(snapshot.officer_role ? [
      `Role scope: ${snapshot.actionable_only ? "tasks my role can act on" : "all roles"}; current role: ${snapshot.officer_role}.`,
      `${snapshot.actionable_tasks} tasks match this role across the complete portfolio. Role eligibility is not personal assignment; case-specific approval limits still apply.`,
    ] : []),
    "",
    ...snapshot.items.flatMap(item => [
      `${PRIORITIES[item.priority].label} · ${item.business_name} · Case #${item.application_id}`,
      item.title, item.reason, ...item.evidence.map(fact => `- ${fact}`), "",
    ]),
    "Snapshot only. Missing records do not prove missed payment. Verify evidence before acting.",
  ].join("\n");
}
