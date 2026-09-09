import { Fragment, useState } from "react";
import { Link } from "react-router-dom";

import { SCORE_BANDS } from "../lib/decisions.js";

const WORKFLOWS = [
  {
    id: "score",
    step: "01",
    pipe: "Score",
    title: "Origination score",
    kicker: "Credit Scoring",
    summary: "Twelve PKR intake fields. A 0–100 ensemble score on the served model.",
    detail:
      "Officers submit applicant, facility, digital receipts, payment history, and cash-flow proxies. The served model uses loan-to-income, payment history, and years in operation. Tenure, inventory, order consistency, existing debt, and headcount are stored and labelled unused. Decisions follow the policy matrix: 0–40 Rejected, 41–70 Manual Review, 71–100 Approved.",
    Icon: GaugeIcon,
  },
  {
    id: "shap",
    step: "02",
    pipe: "SHAP",
    title: "Stored SHAP file",
    kicker: "Explainability",
    summary: "Base plus every contribution reconstructs the displayed score.",
    detail:
      "TreeSHAP attributions are written with the application so a credit file can show why the score moved. Summary cards are rounded so an officer can add them by hand. There is no live bureau connector; payment-history and bureau-balance fields are officer-typed.",
    Icon: ChartIcon,
  },
  {
    id: "ews",
    step: "03",
    pipe: "EWS",
    title: "Early warning",
    kicker: "Surveillance",
    summary: "Alert when the monthly score drops more than 15 points from origination.",
    detail:
      "After disbursement an officer types ageing, bureau balance, and POS inflow. The current score is a published rule on the origination baseline — the ensemble is not re-run. Filters are All, Active, and Resolved. Days-to-default is a 7–365 heuristic, not a validated 60–90 day forecast.",
    Icon: BellIcon,
  },
  {
    id: "register",
    step: "04",
    pipe: "Workspace",
    title: "Officer workspace",
    kicker: "On-premise",
    summary: "JWT login, five routes, every amount in PKR, loopback-only Docker.",
    detail:
      "Dashboard, Credit Scoring, SHAP Reports, EWS Alerts, and Applications share one session. Sign-in issues an 8-hour HS256 token. The stack binds to 127.0.0.1. Designed for SBP-oriented explainability; ForiFlow is not SBP-certified.",
    Icon: ShieldIcon,
  },
];

/**
 * Vertical marketing poster for the officer product — brand tokens, real
 * workflows, and a CTA into the existing /login flow. No signup product exists.
 */
export default function ForiFlowPoster() {
  const [activeId, setActiveId] = useState(WORKFLOWS[0].id);
  const active = WORKFLOWS.find((item) => item.id === activeId) ?? WORKFLOWS[0];

  return (
    <article className="relative mx-auto flex w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950 text-brand-50 shadow-xl sm:aspect-[3/4]">
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        aria-hidden="true"
        style={{
          background:
            "radial-gradient(1200px 420px at 10% -10%, rgb(45 133 96 / 0.45), transparent 55%), radial-gradient(800px 360px at 110% 20%, rgb(31 107 76 / 0.35), transparent 50%)",
        }}
      />

      <header className="relative z-10 flex items-start justify-between gap-3 px-5 pt-5 sm:px-8 sm:pt-6">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500 text-lg font-black text-white">
            F
          </span>
          <div>
            <p className="text-base leading-tight font-bold text-white">ForiFlow</p>
            <p className="text-xs text-brand-200">SME Credit Intelligence</p>
          </div>
        </div>
        <p className="badge border border-brand-700 bg-brand-900/80 text-brand-100">
          On-premise · PKR
        </p>
      </header>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col px-5 pt-5 pb-5 sm:px-8 sm:pt-6 sm:pb-6">
        <p className="text-[11px] font-semibold tracking-[0.18em] text-brand-300 uppercase">
          For Pakistani credit officers
        </p>
        <h1 className="mt-1.5 max-w-lg text-[1.85rem] leading-[1.12] font-black tracking-tight text-white sm:text-[2.15rem]">
          Score the SMEs your bureau file cannot see.
        </h1>
        <p className="mt-2.5 max-w-xl text-sm leading-relaxed text-brand-100">
          Alternative-data origination, a stored SHAP rationale on every decision,
          and post-disbursement early warning — in one officer workspace. No live
          ECIB feed. Not SBP-certified.
        </p>

        <ol className="mt-4 grid grid-cols-3 overflow-hidden rounded-lg text-[10px] font-semibold tracking-wide text-white uppercase sm:text-[11px]">
          {SCORE_BANDS.map((band) => (
            <li
              key={band.decision}
              className={`px-2 py-2 text-center ${
                band.decision === "Manual Review" ? "text-slate-900" : "text-white"
              }`}
              style={{ backgroundColor: band.color }}
            >
              {band.range}
              <span className="mt-0.5 block font-medium normal-case opacity-90">
                {band.decision}
              </span>
            </li>
          ))}
        </ol>

        <PipelineTrack activeId={activeId} onSelect={setActiveId} />

        <div className="mt-3 grid grid-cols-2 gap-2 sm:gap-2.5">
          {WORKFLOWS.map((item) => {
            const selected = item.id === activeId;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveId(item.id)}
                aria-pressed={selected}
                className={`rounded-xl border px-3.5 py-2.5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2 focus-visible:ring-offset-brand-950 ${
                  selected
                    ? "border-brand-400 bg-brand-800 shadow-sm"
                    : "border-brand-800 bg-brand-900/70 hover:border-brand-600 hover:bg-brand-900"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-700 text-brand-100">
                    <item.Icon className="h-4 w-4" />
                  </span>
                  <span className="tabular text-[11px] font-bold text-brand-300">{item.step}</span>
                </span>
                <span className="mt-2 block text-[11px] font-semibold tracking-wide text-brand-300 uppercase">
                  {item.kicker}
                </span>
                <span className="mt-0.5 block text-sm font-semibold text-white">{item.title}</span>
                <span className="mt-1 block text-xs leading-snug text-brand-200">{item.summary}</span>
              </button>
            );
          })}
        </div>

        <div className="mt-3 rounded-xl border border-brand-800 bg-brand-900/80 px-4 py-2.5" aria-live="polite">
          <p className="text-[11px] font-semibold tracking-wide text-brand-300 uppercase">
            {active.kicker}
          </p>
          <p className="mt-1 text-sm leading-relaxed text-brand-50">{active.detail}</p>
        </div>

        <div className="mt-auto pt-4">
          <Link
            to="/login"
            className="btn-primary w-full bg-brand-500 py-3 text-base shadow-lg shadow-brand-950/40 hover:bg-brand-600"
          >
            Sign in to the officer workspace
            <ArrowIcon className="h-4 w-4" />
          </Link>
          <p className="mt-2.5 text-center text-[11px] leading-relaxed text-brand-300">
            Officer JWT · 8-hour session · start.bat on 127.0.0.1 · ForiFlow v1.0
          </p>
        </div>
      </div>
    </article>
  );
}

function PipelineTrack({ activeId, onSelect }) {
  return (
    <div className="mt-3 flex items-center" aria-label="Origination to surveillance pipeline">
      {WORKFLOWS.map((item, index) => (
        <Fragment key={item.id}>
          {index > 0 ? <span className="mx-1.5 h-px min-w-3 flex-1 bg-brand-700" aria-hidden="true" /> : null}
          <button
            type="button"
            onClick={() => onSelect(item.id)}
            aria-pressed={item.id === activeId}
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 ${
              item.id === activeId ? "bg-brand-500 text-white" : "bg-brand-900 text-brand-200 hover:bg-brand-800"
            }`}
          >
            {item.pipe}
          </button>
        </Fragment>
      ))}
    </div>
  );
}

function GaugeIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 18a8 8 0 1116 0" strokeLinecap="round" />
      <path d="M12 18l4.5-5" strokeLinecap="round" />
      <circle cx="12" cy="18" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

function ChartIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 5h10M4 12h14M4 19h7" strokeLinecap="round" />
    </svg>
  );
}

function BellIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M6 9a6 6 0 1112 0c0 4 1.5 5.5 1.5 5.5h-15S6 13 6 9z" strokeLinejoin="round" />
      <path d="M10 18a2 2 0 004 0" strokeLinecap="round" />
    </svg>
  );
}

function ShieldIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M12 3.5l7 3v5.2c0 4.2-2.8 7.2-7 8.8-4.2-1.6-7-4.6-7-8.8V6.5l7-3z" strokeLinejoin="round" />
      <path d="M9 12.2l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ArrowIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
