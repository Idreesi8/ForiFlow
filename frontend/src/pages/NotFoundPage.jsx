import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="card mx-auto max-w-lg px-6 py-12 text-center">
      <p className="text-4xl font-black text-brand-700">404</p>
      <h2 className="mt-2 text-lg font-bold text-slate-900">Page not found</h2>
      <p className="mt-1 text-sm text-slate-500">
        That workspace does not exist. Head back to the portfolio dashboard.
      </p>
      <Link to="/" className="btn-primary mt-5 inline-flex">
        Go to dashboard
      </Link>
    </div>
  );
}
