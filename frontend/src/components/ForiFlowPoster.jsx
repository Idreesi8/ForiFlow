import { Link } from "react-router-dom";

import { SCORE_BANDS } from "../lib/decisions.js";

const PIPELINE = [
  { step: "1", title: "Intake", detail: "12 fields · PKR" },
  { step: "2", title: "Ratios", detail: "currency-invariant" },
  { step: "3", title: "Ensemble", detail: "XGB 0.60 · RF 0.40" },
  { step: "4", title: "SHAP", detail: "TreeExplainer" },
  { step: "5", title: "Decision", detail: "100 × (1 − PD)" },
];

/**
 * Complete A1 FYP poster. Copy matches docs/foriflow-poster.html and the
 * served artefacts in backend/ml/feature_names.json.
 */
export default function ForiFlowPoster() {
  return (
    <article className="mx-auto flex w-full max-w-[1100px] flex-col overflow-visible rounded-xl border border-slate-200 bg-slate-100 text-slate-800 shadow-xl print:max-w-none print:rounded-none print:border-0 print:shadow-none">
      <header className="flex flex-col gap-4 bg-brand-950 px-6 py-5 text-white sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <div className="flex items-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-lg bg-brand-500 text-xl font-black">
            F
          </span>
          <div>
            <h1 className="text-3xl leading-none font-black tracking-tight">ForiFlow</h1>
            <p className="mt-1 max-w-xl text-xs font-medium text-brand-200 sm:text-sm">
              On-premise SME credit scoring, stored SHAP, and rule-based early warning
              for Pakistani credit officers. No live ECIB. Not SBP-certified.
            </p>
          </div>
        </div>
        <p className="text-right text-[11px] leading-relaxed text-brand-200 sm:text-xs">
          <span className="block font-semibold text-white">COMSATS University Islamabad</span>
          BS Business Data Analytics · FYP · 2023–2027
          <br />
          Ramzan Ahmed Idreesi · SP23-BBD-056
          <br />
          Zakria Saeed Abbasi · SP23-BBD-073
          <br />
          Supervisor: Ms. Sarah Tariq
        </p>
      </header>

      <div className="flex flex-col gap-4 px-5 py-5 sm:px-7 sm:py-6">
        <section className="grid grid-cols-2 items-stretch gap-3 lg:grid-cols-4">
          <Kpi value="0.7758">
            Served 5-fold CV AUC-ROC <span className="font-semibold text-brand-700">± 0.0075</span>
            <br />
            hold-out 0.7756 · F1 0.544 · n = 32,581
            <br />
            public/proxy file — not a real SME book
          </Kpi>
          <Kpi value="3">
            Served ensemble features
            <br />
            <span className="font-semibold text-brand-700">
              loan_to_income · payment_history_score · years_in_operation
            </span>
          </Kpi>
          <Kpi value="&gt;15">
            EWS alert if the derived monthly score drops more than 15.0 points from
            origination. Ensemble is not re-run.
          </Kpi>
          <Kpi value="JWT">
            HS256 · 8 hours · roles admin / analyst
            <br />
            <span className="font-semibold text-brand-700">PostgreSQL 16.6 · bind 127.0.0.1</span>
          </Kpi>
        </section>

        <section className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
            <h2 className="text-xs font-extrabold tracking-widest text-brand-900 uppercase">
              Origination pipeline
            </h2>
            <ol className="mt-3 flex items-start">
              {PIPELINE.map((item, index) => (
                <li key={item.step} className="flex min-w-0 flex-1 items-start">
                  {index > 0 ? (
                    <span className="mt-4 h-1 w-2 shrink-0 rounded bg-brand-400 sm:w-3" aria-hidden="true" />
                  ) : null}
                  <div className="min-w-0 flex-1 text-center">
                    <span className="mx-auto flex h-8 w-8 items-center justify-center rounded-full bg-brand-500 text-xs font-black text-white">
                      {item.step}
                    </span>
                    <p className="mt-1.5 text-[11px] font-bold text-brand-900 sm:text-xs">{item.title}</p>
                    <p className="text-[10px] leading-snug text-slate-500 sm:text-[11px]">{item.detail}</p>
                  </div>
                </li>
              ))}
            </ol>
            <ol className="mt-4 grid grid-cols-3 overflow-hidden rounded-md text-[10px] font-bold sm:text-[11px]">
              {SCORE_BANDS.map((band) => (
                <li
                  key={band.decision}
                  className={`px-1 py-2 text-center ${
                    band.decision === "Manual Review" ? "text-slate-900" : "text-white"
                  }`}
                  style={{ backgroundColor: band.color }}
                >
                  {band.range}
                  <span className="mt-0.5 block font-semibold">{band.decision}</span>
                </li>
              ))}
            </ol>
            <p className="mt-3 text-[11px] leading-relaxed text-slate-600 sm:text-xs">
              Relative ranking after SMOTE-in-CV, not a calibrated PD. Tenure, inventory
              turnover, order consistency, existing debt, and headcount are stored with an
              amber unused label. loan_to_income uses facility vs annual turnover proxy
              max(digital receipts, cash-flow) × 12. SHAP summary cards are display-rounded
              so they add to the 1-decimal score. AUC-ROC 0.85 is a bank-data target. The
              three-feature ladder last step was 0.7776 ± 0.0067 (XGB 0.65 / RF 0.35) and
              was not shipped.
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
            <h2 className="text-xs font-extrabold tracking-widest text-brand-900 uppercase">
              On-premise stack
            </h2>
            <div className="mt-3 space-y-2 text-sm font-semibold">
              <p className="flex flex-col gap-0.5 rounded-lg bg-brand-50 px-3 py-2.5 text-brand-900 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
                React 18 officer workspace
                <span className="text-xs font-medium whitespace-nowrap text-slate-500">nginx · :3000 · /login</span>
              </p>
              <p className="flex flex-col gap-0.5 rounded-lg bg-brand-900 px-3 py-2.5 text-white sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
                FastAPI + served pickles
                <span className="text-xs font-medium whitespace-nowrap text-brand-200">uvicorn · :8000 · /api</span>
              </p>
              <p className="flex flex-col gap-0.5 rounded-lg bg-brand-800 px-3 py-2.5 text-white sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
                PostgreSQL 16.6
                <span className="text-xs font-medium whitespace-nowrap text-brand-300">127.0.0.1:5432 · Alembic</span>
              </p>
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-slate-600 sm:text-xs">
              Everyday start is <strong>start.bat / start.ps1</strong> (starts Docker Desktop
              if needed; no rebuild). Compose needs POSTGRES_* and JWT_SECRET_KEY. Seed with{" "}
              <em>python -m scripts.seed_admin</em> only if start.ps1 reports no officer. GET
              /health is public. /score, /explain, and /ews require a Bearer token. pytest uses
              in-memory SQLite. Five routes after login: Dashboard, Credit Scoring, SHAP
              Reports, EWS Alerts, Applications.
            </p>
          </div>
        </section>

        <section className="grid gap-3 sm:grid-cols-3">
          <Figure src="/fyp-poster/03-score-result.png" caption="Fig. 1 — Credit Scoring: 0–100 gauge, unused-field labels, additive SHAP waterfall." alt="Credit scoring result with SHAP waterfall" />
          <Figure src="/fyp-poster/01-dashboard.png" caption="Fig. 2 — Dashboard after JWT login: origination mix and EWS strip." alt="Officer dashboard after JWT login" />
          <Figure src="/fyp-poster/05-ews-alerts.png" caption="Fig. 3 — EWS Alerts: All / Active / Resolved. In Review is backend-only." alt="EWS alerts with All Active Resolved filters" />
        </section>

        <section className="grid gap-3 sm:grid-cols-5">
          <Figure className="sm:col-span-3" src="/fyp-poster/architecture-delivered.png" caption="Fig. 4 — Delivered architecture: intake → ensemble → decision → dashboard / API → EWS." alt="Delivered prototype architecture" />
          <Figure className="sm:col-span-2" src="/fyp-poster/04-shap-chart.png" caption="Fig. 5 — SHAP Reports: stored TreeSHAP file on the credit application." alt="SHAP reports workspace" />
        </section>

        <section className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <h2 className="text-xs font-extrabold tracking-widest text-brand-900 uppercase">Early warning</h2>
            <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-slate-700 sm:text-xs">
              <li>Officer types month, ageing bucket, bureau balance, POS inflow (no live ECIB).</li>
              <li>Current score is a published rule on the origination baseline — ageing, leverage, POS coverage. The ensemble is not re-run.</li>
              <li>Alert if drop &gt; 15.0. Filters: All / Active / Resolved.</li>
              <li>Days-to-default is a 7–365 heuristic from ageing + excess drop, not a validated 60–90 day forecast.</li>
            </ul>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <h2 className="text-xs font-extrabold tracking-widest text-brand-900 uppercase">What the model uses</h2>
            <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-slate-700 sm:text-xs">
              <li>Winner: credit_risk_shared (21.82% default rate, 3 shared features).</li>
              <li>Rejected candidates: combined_shared CV 0.652 · loan_default_full CV 0.622.</li>
              <li>Give Me Some Credit 0.8656 is a proxy experiment on a different file, not this served model.</li>
              <li>Linear surrogate only if ensemble pickles are missing.</li>
            </ul>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <h2 className="text-xs font-extrabold tracking-widest text-brand-900 uppercase">Pilot access</h2>
            <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-slate-700 sm:text-xs">
              <li>http://127.0.0.1:3000 dashboard</li>
              <li>http://127.0.0.1:8000 API</li>
              <li>start.bat / start.ps1 · loopback only</li>
              <li>github.com/Idreesi8/ForiFlow</li>
              <li>ForiFlow v1.0 · PKR</li>
            </ul>
            <Link to="/login" className="btn-primary mt-4 w-full">
              Sign in to the officer workspace
            </Link>
          </div>
        </section>
      </div>

      <footer className="flex flex-col gap-2 bg-brand-950 px-6 py-3 text-[11px] leading-relaxed text-brand-200 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <span>
          ForiFlow v1.0 · start.bat · 127.0.0.1 · JWT HS256 · PKR · officer-typed bureau
          fields · SHAP stored per decision · not SBP-certified
        </span>
        <a className="font-semibold text-brand-300 hover:text-white" href="https://github.com/Idreesi8/ForiFlow">
          github.com/Idreesi8/ForiFlow
        </a>
      </footer>
    </article>
  );
}

function Kpi({ value, children }) {
  return (
    <div className="flex h-full flex-col rounded-xl border border-slate-200 bg-white px-3.5 py-3">
      <p className="text-2xl leading-none font-black tracking-tight text-brand-950 sm:text-3xl">{value}</p>
      <p className="mt-2 text-[11px] leading-snug text-slate-600">{children}</p>
    </div>
  );
}

function Figure({ src, caption, alt, className = "" }) {
  return (
    <figure className={`flex min-w-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white ${className}`}>
      <div className="flex min-h-[220px] flex-1 items-center justify-center bg-slate-100 p-2 sm:min-h-[260px]">
        <img src={src} alt={alt} className="max-h-[260px] w-auto max-w-full object-contain sm:max-h-[300px]" />
      </div>
      <figcaption className="border-t border-slate-200 px-3 py-2 text-[10px] leading-snug text-slate-500 sm:text-[11px]">
        {caption}
      </figcaption>
    </figure>
  );
}
