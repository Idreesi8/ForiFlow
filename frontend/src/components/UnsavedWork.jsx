import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import { useBlocker, useLocation } from "react-router-dom";
import { containDialogFocus } from "../lib/dialogFocus.js";

const WorkContext = createContext(null);

export function UnsavedWorkProvider({ children }) {
  const entries = useRef(new Map());
  const bypass = useRef(false);
  const [work, setWork] = useState([]);
  const [exit, setExit] = useState(null);
  const dialog = useRef(null);
  const stay = useRef(null);
  const location = useLocation();
  const register = useCallback((id, value) => {
    if (value && (value.dirty || value.busy)) entries.current.set(id, value);
    else entries.current.delete(id);
    setWork([...entries.current.values()]);
  }, []);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => !bypass.current &&
    currentLocation.pathname !== nextLocation.pathname && entries.current.size > 0);
  const busy = work.some(item => item.busy);
  const blocked = blocker.state === 'blocked' || Boolean(exit);
  const requestExit = useCallback(action => {
    if (entries.current.size) setExit({ run: action });
    else action();
  }, []);
  const cancel = () => { setExit(null); if (blocker.state === 'blocked') blocker.reset(); };
  const proceed = () => {
    if (busy) return;
    if (exit) {
      bypass.current = true;
      const action = exit.run;
      setExit(null);
      action();
    } else if (blocker.state === 'blocked') blocker.proceed();
  };
  useEffect(() => { bypass.current = false; }, [location.key]);
  useEffect(() => {
    if (!blocked) return;
    const previous = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current.showModal();
    stay.current.focus();
    return () => { dialog.current?.close(); document.body.style.overflow = previousOverflow; previous?.focus(); };
  }, [blocked]);
  useEffect(() => {
    if (!work.length || bypass.current) return;
    const warn = event => { if (!bypass.current) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [work.length]);
  useEffect(() => {
    if (blocked && !work.length) proceed();
  }, [blocked, work.length]);

  return <WorkContext.Provider value={{ register, requestExit }}>
    {children}
    <dialog ref={dialog} className="workspace-dialog" aria-labelledby="unsaved-work-title"
      onCancel={event => { event.preventDefault(); cancel(); }}
      onKeyDown={containDialogFocus}>
      <div className="p-6 sm:p-7">
        <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-amber-50 text-xl text-amber-800" aria-hidden="true">↩</span>
        <h2 id="unsaved-work-title" className="text-xl font-bold text-slate-900">{busy ? 'Work is still in progress' : exit ? 'Sign out and discard your entries?' : 'Leave this page?'}</h2>
        <p className="mt-3 text-sm leading-relaxed text-slate-600">{busy ? 'Wait for the current operation to finish. Stay here to check its result or cancel a statement read.' : 'There are unsaved figures or notes on this page. Stay here to keep editing, or leave and discard these entries.'}</p>
        <ul className="my-4 space-y-2 rounded-xl bg-slate-50 p-4 text-sm text-slate-800">{work.map((item, index) => <li key={index}>• {item.label}{item.busy ? ' — in progress' : ''}{item.leaveWarning ? <p className="mt-2 text-sm leading-relaxed text-amber-950">{item.leaveWarning}</p> : null}</li>)}</ul>
        <p className="text-xs leading-relaxed text-slate-500">Entries stay only in this tab. This does not create a saved draft or recover work after a browser crash. Existing saved records stay on file.</p>
        <div className="mt-6 flex flex-wrap gap-3"><button ref={stay} type="button" className="btn-primary" onClick={cancel}>Stay here</button><button type="button" className="btn-secondary" disabled={busy} onClick={proceed}>{exit ? 'Sign out and discard' : 'Leave and discard'}</button></div>
      </div>
    </dialog>
  </WorkContext.Provider>;
}

export function useUnsavedWork({ label, dirty, busy = false, leaveWarning = null }) {
  const id = useId();
  const { register } = useContext(WorkContext);
  useEffect(() => {
    register(id, { label, dirty, busy, leaveWarning });
    return () => register(id, null);
  }, [register, id, label, dirty, busy, leaveWarning]);
}

export function useGuardedExit() {
  return useContext(WorkContext).requestExit;
}
