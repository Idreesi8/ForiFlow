/** Small shared blocks for loading, error and empty states. */

export function Spinner({ className = "h-5 w-5" }) {
  return (
    <svg
      className={`animate-spin text-brand-600 ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-90"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}

export function LoadingState({ label = "Loading…" }) {
  return (
    <div
      className="flex items-center justify-center gap-3 px-6 py-12 text-sm text-slate-500"
      role="status"
    >
      <Spinner />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="m-5 rounded-lg border border-rose-200 bg-rose-50 px-4 py-4 text-sm text-rose-800">
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="mt-0.5 text-lg leading-none">
          ⚠
        </span>
        <div className="flex-1">
          <p className="font-semibold">Request failed</p>
          <p className="mt-1 text-rose-700">{message}</p>
          {onRetry ? (
            <button type="button" onClick={onRetry} className="btn-secondary mt-3">
              Try again
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function EmptyState({ title, description, action }) {
  return (
    <div className="px-6 py-12 text-center">
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      {description ? (
        <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">{description}</p>
      ) : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
