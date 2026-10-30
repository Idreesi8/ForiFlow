export const MONITORING_SECTIONS = [
  { id: 'portfolio-monitoring', label: 'Portfolio', hint: 'See what needs attention' },
  { id: 'facility-history', label: 'Facility history', hint: 'Understand the recorded evidence' },
  { id: 'monitoring', label: 'Record a month', hint: 'Enter verified figures' },
  { id: 'alert-queue', label: 'Alert queue', hint: 'Review and follow up' },
];

/** In-page movement keeps the mounted editor and its unsaved figures intact. */
export function revealMonitoringSection(id) {
  if (!MONITORING_SECTIONS.some(section => section.id === id)) return;
  requestAnimationFrame(() => {
    const target = document.getElementById(id);
    if (!target) return;
    target.scrollIntoView({ block: 'start' });
    target.focus({ preventScroll: true });
  });
}
