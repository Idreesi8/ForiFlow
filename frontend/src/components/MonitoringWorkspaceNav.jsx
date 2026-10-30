import { Link, useLocation } from 'react-router-dom';
import { MONITORING_SECTIONS, revealMonitoringSection } from '../lib/monitoringWorkspace.js';

export default function MonitoringWorkspaceNav({ selectedId, overview, dirty, busy }) {
  const location = useLocation();
  const details = {
    'portfolio-monitoring': overview ? `${overview.monitored_facilities} monitored ${overview.monitored_facilities === 1 ? 'facility' : 'facilities'}` : 'Portfolio position',
    'facility-history': selectedId ? `Case #${selectedId}` : 'Choose a facility',
    monitoring: busy ? 'Saving figures…' : dirty ? 'Unsaved figures in this tab' : 'Enter verified figures',
    'alert-queue': overview ? `${overview.open_alerts} open · portfolio` : 'Review and follow up',
  };
  return <nav aria-label="Monitoring workspace shortcuts" className="monitoring-shortcuts print:hidden">
    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
      {MONITORING_SECTIONS.map((section, index) => {
        const active = location.hash === `#${section.id}`;
        return <Link key={section.id}
          to={{ pathname: location.pathname, search: location.search, hash: `#${section.id}` }}
          state={location.state} preventScrollReset
          aria-current={active ? 'location' : undefined}
          onClick={event => {
            if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey)
              revealMonitoringSection(section.id);
          }}
          className={`flex min-h-12 min-w-0 items-center gap-2 rounded-xl px-2.5 py-2 text-sm transition ${active ? 'bg-brand-600 text-white' : 'text-slate-700 hover:bg-brand-50'}`}>
          <span aria-hidden="true" className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${active ? 'bg-white/20' : 'bg-slate-100 text-slate-500'}`}>{index + 1}</span>
          <span className="min-w-0"><span className="block text-xs font-semibold sm:text-sm">{section.label}</span>
            <span className={`mt-0.5 hidden text-[11px] sm:block ${active ? 'text-brand-50' : 'text-slate-500'}`}>{details[section.id]}</span></span>
        </Link>;
      })}
    </div>
    {dirty || busy ? <p role="status" className="px-3 pb-1 pt-2 text-xs text-brand-800">{busy ? 'Saving monitoring figures. Wait for the result.' : 'Your monitoring figures are unsaved. You can move between these sections and keep editing.'}</p> : null}
  </nav>;
}
