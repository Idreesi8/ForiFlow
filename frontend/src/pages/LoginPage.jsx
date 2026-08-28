import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { storeSession, isLoggedIn } from "../api/auth.js";
import { apiErrorMessage, login } from "../api/client.js";

/** Minimal on-premise sign-in. The dashboard is unusable without a JWT. */
export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (isLoggedIn()) {
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const session = await login(username.trim(), password);
      storeSession(session);
      navigate(from, { replace: true });
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Sign-in failed."));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center justify-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-lg bg-brand-600 text-xl font-black text-white">
            F
          </span>
          <div>
            <p className="text-lg font-bold text-slate-900">ForiFlow</p>
            <p className="text-xs text-slate-500">SME Credit Intelligence</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="card px-6 py-7">
          <h1 className="text-lg font-bold text-slate-900">Sign in</h1>
          <p className="mt-1 text-sm text-slate-500">
            On-premise officer accounts only. Tokens expire after 8 hours.
          </p>

          <label className="field-label mt-6" htmlFor="username">
            Username
          </label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            className="field-input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />

          <label className="field-label mt-4" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            className="field-input"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />

          {error ? (
            <p className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
              {error}
            </p>
          ) : null}

          <button type="submit" className="btn-primary mt-6 w-full" disabled={isSubmitting}>
            {isSubmitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
