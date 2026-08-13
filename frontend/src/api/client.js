import axios from "axios";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { "Content-Type": "application/json" },
});

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
    return `Cannot reach the ForiFlow API at ${API_BASE_URL}. Start the backend with "uvicorn main:app --port 8000".`;
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

export const fetchApplication = (applicationId) =>
  client.get(`/score/applications/${applicationId}`).then((response) => response.data);

export const explainApplication = (applicationId, { refresh = false } = {}) =>
  client
    .post(`/explain/${applicationId}`, null, { params: { refresh } })
    .then((response) => response.data);

export const fetchAlerts = (params = {}) =>
  client.get("/ews/alerts", { params }).then((response) => response.data);

export const resolveAlert = (alertId) =>
  client.patch(`/ews/alerts/${alertId}/resolve`).then((response) => response.data);

export const fetchBorrowerHistory = (borrowerId) =>
  client.get(`/ews/borrowers/${borrowerId}/history`).then((response) => response.data);

export const monitorBorrower = (payload) =>
  client.post("/ews/monitor", payload).then((response) => response.data);

export const fetchHealth = () =>
  client.get("/health", { timeout: 4000 }).then((response) => response.data);

export default client;
