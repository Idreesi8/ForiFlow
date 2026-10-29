import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { storeSession, isLoggedIn } from "../api/auth.js";
import { apiErrorMessage, login } from "../api/client.js";

/** Minimal on-premise sign-in. The dashboard is unusable without a JWT. */
export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const destination = location.state?.from;
  const from = destination?.pathname?.startsWith("/") && !destination.pathname.startsWith("//") && destination.pathname !== "/login"
    ? destination.pathname + (destination.search ?? "") + (destination.hash ?? "") : "/";
  const sessionEnded = new URLSearchParams(location.search).get("session") === "expired";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);

  useEffect(() => { document.title = "Sign in · ForiFlow"; }, []);

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
    <div className="min-h-screen bg-white lg:grid lg:grid-cols-2">
      <aside className="relative hidden overflow-hidden bg-brand-950 px-12 py-12 text-white lg:flex lg:flex-col xl:px-20">
        <div aria-hidden="true" className="pointer-events-none absolute -right-40 top-28 h-[600px] w-[600px] rounded-full border border-brand-800/50 shadow-[0_0_0_80px_rgba(45,133,96,0.06),0_0_0_160px_rgba(45,133,96,0.04)]" />
        <div className="relative flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-500 text-xl font-black">F</span><div><p className="text-lg font-bold">ForiFlow</p><p className="text-xs text-brand-200">SME Credit Intelligence</p></div></div>
        <div className="relative my-auto max-w-lg py-16">
          <p className="mb-5 text-xs font-semibold tracking-[0.2em] text-brand-300 uppercase">Clarity at every step</p>
          <h2 className="text-4xl leading-tight font-semibold tracking-tight xl:text-5xl">A clearer view.<br /><span className="text-brand-300">A better next step.</span></h2>
          <p className="mt-6 max-w-sm text-base leading-relaxed text-brand-100">Assess a business, understand its score and stay on top of the cases that need your attention.</p>
          <div className="mt-10 space-y-4">
            {[
              ["01", "Assess with evidence", "Keep business details and financial inputs together."],
              ["02", "Understand the recommendation", "Review the score explanation before a decision."],
              ["03", "Follow through", "Track recorded months and prioritise follow-ups."],
            ].map(([number, title, detail]) => <div key={number} className="flex items-start gap-4 rounded-xl border border-brand-700/50 bg-brand-900/70 px-5 py-4"><span className="pt-0.5 text-xs font-semibold text-brand-300">{number}</span><div><p className="text-sm font-semibold">{title}</p><p className="mt-1 text-xs leading-relaxed text-brand-200">{detail}</p></div></div>)}
          </div>
        </div>
        <p className="relative text-xs text-brand-200">Built around your credit workflow · All amounts in PKR</p>
      </aside>
      <main className="flex min-h-screen items-center justify-center px-6 py-10 sm:px-10">
      <div className="w-full max-w-sm">
        <div className="mb-10 flex items-center gap-3 lg:hidden">
          <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600 text-xl font-black text-white">
            F
          </span>
          <div>
            <p className="text-lg font-bold text-slate-900">ForiFlow</p>
            <p className="text-xs text-slate-500">SME Credit Intelligence</p>
          </div>
        </div>

        <p className="mb-3 text-xs font-semibold tracking-[0.16em] text-brand-700 uppercase">Your officer workspace</p>
        <form onSubmit={handleSubmit}>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Sign in</h1>
          <p className="mt-3 text-sm leading-relaxed text-slate-500">Welcome back. Use your ForiFlow account to continue.</p>

          {sessionEnded && !error ? (
            <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
              Your session has ended. Please sign in again.
            </p>
          ) : null}

          <label className="field-label mt-6" htmlFor="username">
            Username
          </label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            autoFocus
            disabled={isSubmitting}
            className="field-input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />

          <label className="field-label mt-4" htmlFor="password">
            Password
          </label>
          <div className="relative">
          <input
            id="password"
            name="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            className="field-input pr-20"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            onKeyUp={event => setCapsLock(Boolean(event.getModifierState?.("CapsLock")))}
            onBlur={() => setCapsLock(false)}
            disabled={isSubmitting}
            required
          />
          <button type="button" aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}
            className="absolute inset-y-0 right-1 min-w-16 rounded-lg px-3 text-xs font-semibold text-brand-700 hover:bg-brand-50" onClick={() => setShowPassword(value => !value)}>{showPassword ? "Hide" : "Show"}</button>
          </div>
          {capsLock ? <p role="status" className="mt-2 text-xs text-amber-800">Caps Lock is on.</p> : null}

          {error ? (
            <p className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
              {error}
            </p>
          ) : null}

          <button type="submit" className="btn-primary mt-6 w-full" disabled={isSubmitting}>
            {isSubmitting ? "Signing in…" : "Sign in"}<span aria-hidden="true">→</span>
          </button>
          <p className="mt-5 text-xs leading-relaxed text-slate-500">Need access or a password reset? Contact the person who manages your ForiFlow accounts.</p>
          <details className="mt-8 border-t border-slate-200 pt-5 text-xs text-slate-500"><summary className="font-semibold text-slate-600">About your session</summary><p className="mt-3 leading-relaxed">Sessions expire after 8 hours. Five wrong passwords lock the username for 15 minutes. Sign out when you finish on a shared device.</p></details>
        </form>
      </div>
      </main>
    </div>
  );
}
