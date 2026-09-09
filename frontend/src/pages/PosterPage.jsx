import ForiFlowPoster from "../components/ForiFlowPoster.jsx";

/** Public marketing view of the officer poster. No JWT required. */
export default function PosterPage() {
  return (
    <div className="min-h-screen bg-slate-100 px-4 py-8 sm:py-12">
      <ForiFlowPoster />
    </div>
  );
}
