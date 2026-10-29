import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { containDialogFocus } from "../lib/dialogFocus.js";

/** Search destinations locally; borrower records are never searched or cached here. */
export default function WorkspaceFinder({ items, open, onClose }) {
  const dialog = useRef(null);
  const input = useRef(null);
  const results = useRef(null);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches = items.filter(item => words.every(word =>
    `${item.label} ${item.description} ${item.keywords ?? ""}`.toLocaleLowerCase().includes(word)));

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    setQuery("");
    dialog.current.showModal();
    input.current.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { dialog.current?.close(); document.body.style.overflow = previousOverflow; previous?.focus(); };
  }, [open]);

  const choose = to => { onClose(); navigate(to); };
  const move = (event, direction) => {
    const buttons = [...results.current.querySelectorAll("button")];
    if (!buttons.length) return;
    event.preventDefault();
    const current = buttons.indexOf(document.activeElement);
    buttons[(current + direction + buttons.length) % buttons.length].focus();
  };

  return <dialog ref={dialog} aria-labelledby="workspace-finder-title" className="workspace-dialog"
    onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); onClose(); } else containDialogFocus(event); }}
    onCancel={onClose} onClick={event => { if (event.target === dialog.current) onClose(); }}>
    <div className="border-b border-slate-200 p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 id="workspace-finder-title" className="font-bold text-slate-900">Find a workspace</h2>
        <button type="button" className="btn-ghost min-h-9 px-2 text-xs" onClick={onClose}>Close <kbd className="rounded border border-slate-200 px-1.5 py-0.5">Esc</kbd></button>
      </div>
      <label htmlFor="workspace-search" className="sr-only">Search workspaces</label>
      <input ref={input} id="workspace-search" type="search" autoComplete="off" className="field-input"
        placeholder="Try assessment, payments or policy…" value={query} onChange={event => setQuery(event.target.value)}
        onKeyDown={event => {
          if (event.key === "ArrowDown") move(event, 1);
          if (event.key === "Enter" && matches.length) { event.preventDefault(); choose(matches[0].to); }
        }} />
      <p className="mt-2 text-xs text-slate-500">Search pages and tools. Look up individual cases in Applications.</p>
    </div>
    <div ref={results} className="max-h-[55dvh] overflow-y-auto p-2" onKeyDown={event => {
      if (event.key === "ArrowDown") move(event, 1);
      if (event.key === "ArrowUp") move(event, -1);
    }}>
      {matches.map(({ to, label, description, icon: Icon }) => <button key={to} type="button" onClick={() => choose(to)}
        className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left hover:bg-brand-50 focus-visible:bg-brand-50">
        <span className="rounded-lg bg-brand-50 p-2 text-brand-700"><Icon className="h-5 w-5" /></span>
        <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-slate-900">{label}</span><span className="mt-0.5 block text-xs leading-relaxed text-slate-500">{description}</span></span>
        <span className="text-slate-400" aria-hidden="true">→</span>
      </button>)}
      {!matches.length ? <div className="px-4 py-10 text-center"><p className="font-semibold text-slate-800">No workspace found</p><p className="mt-2 text-sm text-slate-500">Try a shorter word, such as score, alert or team.</p></div> : null}
    </div>
    <p role="status" className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">{matches.length} workspaces · Use ↑ ↓ to move and Enter to open</p>
  </dialog>;
}
