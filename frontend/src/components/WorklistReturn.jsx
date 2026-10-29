import { Link, useLocation } from "react-router-dom";
import { worklistReturnPath } from "../lib/actionDesk.js";
import { reminderReturnState } from '../lib/reminderReview.js';

export default function WorklistReturn() {
  const location = useLocation();
  const reminder = reminderReturnState(location.state);
  const target = reminder ? `/reminders${reminder.reminderSearch?'?'+reminder.reminderSearch:''}` : worklistReturnPath(location.state);
  if (!target) return null;
  return <nav aria-label="Return to worklist" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-900 print:hidden">
    <Link className="font-semibold underline underline-offset-4" to={target}>{reminder?'← Back to reminders':'← Back to worklist'}</Link>
    <span className="text-xs">{reminder?'Return with your reminder filters preserved.':'Return with your filters and page preserved.'}</span>
  </nav>;
}
