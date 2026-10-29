import { Component } from "react";

/** Keep navigation available if a downloaded page cannot load or render. */
export default class PageBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section className="m-5 rounded-lg border border-rose-200 bg-rose-50 p-5 text-sm text-rose-900" role="alert">
        <h2 className="font-semibold">This page could not load</h2>
        <p className="mt-2">
          Reload the page to try again. If this keeps happening, contact your administrator.
        </p>
        <button type="button" className="btn-secondary mt-4" onClick={() => window.location.reload()}>
          Reload page
        </button>
      </section>
    );
  }
}
