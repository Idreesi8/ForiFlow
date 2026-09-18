import ForiFlowPoster from "../components/ForiFlowPoster.jsx";

/** Public A1 FYP poster. No JWT required. Print from docs/foriflow-poster.html. */
export default function PosterPage() {
  return (
    <div className="min-h-screen bg-slate-300 px-3 py-6 sm:px-6 sm:py-10">
      <ForiFlowPoster />
    </div>
  );
}
