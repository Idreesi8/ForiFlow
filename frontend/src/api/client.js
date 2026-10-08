import axios from "axios";

import { clearSession, getToken } from "./auth.js";

// Relative by default so the dashboard works unchanged in both deployments:
// nginx proxies /api to the backend container, and `vite dev` proxies the same
// prefix to localhost:8000. Set VITE_API_BASE_URL to point at an absolute host.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

/** Absolute URL for display, since "/api" alone tells an officer nothing. */
export const API_BASE_LABEL =
  API_BASE_URL.startsWith("/") && typeof window !== "undefined"
    ? `${window.location.origin}${API_BASE_URL}`
    : API_BASE_URL;

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { "Content-Type": "application/json" },
});

client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const requestUrl = String(error.config?.url ?? "");
    const isLogin = requestUrl.includes("/auth/login");
    if (status === 401 && !isLogin) {
      clearSession();
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  },
);

/**
 * Turn an Axios failure into a sentence a credit officer can act on.
 * FastAPI returns validation errors as a list of `{loc, msg}` objects and
 * business errors as a plain `detail` string.
 */
export function apiErrorMessage(error, fallback = "Something went wrong.") {
  if (!error) return fallback;

  if (error.code === "ECONNABORTED") {
    return "The request timed out. Please check that the ForiFlow API is running.";
  }

  if (!error.response) {
    return `Cannot reach the ForiFlow API at ${API_BASE_LABEL}. Check the backend is up ("docker compose ps", or "uvicorn main:app --port 8000" for a local run).`;
  }

  const { status, data } = error.response;
  const detail = data?.detail;

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null;
        return field ? `${field}: ${item.msg}` : item.msg;
      })
      .join(" • ");
  }

  if (typeof detail === "string") return detail;
  return `${fallback} (HTTP ${status})`;
}

export const scoreApplication = (payload) =>
  client.post("/score", payload).then((response) => response.data);

export const fetchApplications = (params = {}) =>
  client.get("/score/applications", { params }).then((response) => response.data);

export const fetchPortfolioStats = () =>
  client.get("/score/stats").then((response) => response.data);

export const fetchApplication = (applicationId) =>
  client.get(`/score/applications/${applicationId}`).then((response) => response.data);

export const explainApplication = (applicationId, { refresh = false } = {}) =>
  client
    .post(`/explain/${applicationId}`, null, { params: { refresh } })
    .then((response) => response.data);

export const fetchAlerts = (params = {}) =>
  client.get("/ews/alerts", { params }).then((response) => response.data);

export const reviewApplication = (applicationId, { decision, note }) =>
  client
    .post(`/score/applications/${applicationId}/review`, { decision, note })
    .then((response) => response.data);

/** Record the officer's decision: "Approved", "Rejected" or "Escalated". */
export const decideApplication = (applicationId, payload) =>
  client
    .post(`/score/applications/${applicationId}/decision`, payload)
    .then((response) => response.data);

export const fetchActivePolicy = () =>
  client.get("/policy/active").then((response) => response.data);

export const fetchPolicyVersions = () =>
  client.get("/policy/versions").then((response) => response.data);

export const createPolicyVersion = (payload) =>
  client.post("/policy/versions", payload).then((response) => response.data);

export const activatePolicyVersion = (policyId) =>
  client.post(`/policy/versions/${policyId}/activate`).then((response) => response.data);

// --- Early Warning System (2.1) ---------------------------------------------------
// The backend is authoritative for every EWS fact: state, trend, severity and
// reasons. The dashboard only shows them.

/** Record a month. 409 when the month is already on file (see correctObservation). */
export const recordObservation = (payload) =>
  client.post("/ews/observations", payload).then((response) => response.data);

/** Pre-2.1 name for recordObservation. */
export const monitorBorrower = recordObservation;

/** Correct a recorded month (manager or admin). The original is kept, superseded. */
export const correctObservation = (observationId, payload) =>
  client
    .post(`/ews/observations/${observationId}/correct`, payload)
    .then((response) => response.data);

export const fetchFacilityObservations = (facilityId, params = {}) =>
  client
    .get(`/ews/facilities/${facilityId}/observations`, { params })
    .then((response) => response.data);

export const fetchFacilityTrend = (facilityId) =>
  client.get(`/ews/facilities/${facilityId}/trend`).then((response) => response.data);

export const fetchFacilityState = (facilityId) =>
  client.get(`/ews/facilities/${facilityId}/state`).then((response) => response.data);

export const fetchFacilityTimeline = (facilityId) =>
  client.get(`/ews/facilities/${facilityId}/timeline`).then((response) => response.data);

export const fetchEwsOverview = () => client.get("/ews/overview").then((response) => response.data);

export const fetchAlertHistory = (alertId) =>
  client.get(`/ews/alerts/${alertId}/history`).then((response) => response.data);

/**
 * One lifecycle step on an alert (manager or admin): "acknowledge", "assign",
 * "due-date", "action-required", "resolve" or "dismiss".
 */
export const alertLifecycle = (alertId, step, payload = {}) =>
  client.post(`/ews/alerts/${alertId}/${step}`, payload).then((response) => response.data);

export const fetchBorrowerHistory = (borrowerId) =>
  client.get(`/ews/borrowers/${borrowerId}/history`).then((response) => response.data);

export const summariseStatement = (csv) =>
  client.post("/score/statement", { csv }).then((response) => response.data);

export const fetchReminders = () =>
  client.get("/portfolio/reminders").then((response) => response.data);

export const fetchUsers = () => client.get("/auth/users").then((response) => response.data);

export const createUser = (payload) =>
  client.post("/auth/users", payload).then((response) => response.data);

export const fetchPortfolioSummary = () =>
  client.get("/portfolio/summary").then((response) => response.data);

export const fetchModelEvaluation = () =>
  client.get("/model/evaluation").then((response) => response.data);

export const fetchDrift = () => client.get("/model/drift").then((response) => response.data);

export const fetchFairness = () =>
  client.get("/model/fairness").then((response) => response.data);

export const fetchEarlyWarningModel = () =>
  client.get("/model/early-warning").then((response) => response.data);

export const fetchModelCard = () => client.get("/model/card").then((response) => response.data);

export const fetchFeatureContract = () =>
  client.get("/model/feature-contract").then((response) => response.data);

export const fetchDataQuality = () =>
  client.get("/model/data-quality").then((response) => response.data);

export const fetchModelComparison = () =>
  client.get("/model/comparison").then((response) => response.data);

export const fetchHealth = () =>
  client.get("/health", { timeout: 4000 }).then((response) => response.data);

export const login = (username, password) =>
  client.post("/auth/login", { username, password }).then((response) => response.data);

export default client;
