# Guided monitoring workspace

The EWS workspace has four section shortcuts: Portfolio, Facility history,
Record a month and Alert queue. They remain available while scrolling. Moving
between sections keeps the month editor mounted and retains unsubmitted figures.
The current section has a URL fragment, so Back returns to the previous section.
Focused case, reporting-month query parameters and worklist return context are
preserved by the shortcuts.

On narrow screens, monitored facilities appear as cards with their recorded
state, baseline, latest score, change, source, month and open-alert status.
View history and Record month open the selected facility's relevant section.
The desktop table offers the same actions as keyboard-operable buttons.

Switching facilities with unsubmitted figures opens a focused dialog. Keep
editing and Escape retain the current facility and figures; confirming discards
the unsubmitted figures and opens the requested facility and section. A save in
progress blocks switching. Section navigation waits for preceding history and
calendar content to finish loading before completing its scroll position.

These are navigation and presentation changes. Monitoring calculations,
permissions, stored observations and the alert lifecycle use the existing API.
