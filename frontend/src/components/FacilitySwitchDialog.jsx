import { useEffect, useRef } from 'react';
import { containDialogFocus } from '../lib/dialogFocus.js';

export default function FacilitySwitchDialog({ fromId, toId, busy, onCancel, onConfirm }) {
  const dialog = useRef(null);
  const stay = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current.showModal();
    stay.current.focus();
    return () => {
      dialog.current?.close();
      document.body.style.overflow = previousOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return <dialog ref={dialog} className="workspace-dialog" aria-labelledby="facility-switch-title"
    aria-describedby="facility-switch-description" onKeyDown={containDialogFocus}
    onCancel={event => { event.preventDefault(); onCancel(); }}>
    <div className="max-h-[80dvh] overflow-y-auto p-5 sm:p-6">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">Unsaved monitoring figures</p>
      <h2 id="facility-switch-title" className="mt-2 text-xl font-bold text-slate-900">Switch to case #{toId}?</h2>
      <p id="facility-switch-description" className="mt-3 text-sm leading-relaxed text-slate-600">Case #{fromId} has unsubmitted figures. Switching clears those entries. Keep editing to finish this month first.</p>
      {busy ? <p role="status" className="mt-3 text-sm text-amber-800">A save is in progress. Wait for its result before switching.</p> : null}
      <div className="mt-5 flex flex-wrap gap-3">
        <button ref={stay} type="button" className="btn-primary" onClick={onCancel}>Keep editing this facility</button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={onConfirm}>Switch facility and clear figures</button>
      </div>
    </div>
  </dialog>;
}
