import { useEffect, useState } from "react";
import { businessDate } from "../lib/format.js";

/** Keep date-input limits current across Pakistan midnight and laptop sleep. */
export function useBusinessDate() {
  const [day, setDay] = useState(() => businessDate());
  useEffect(() => {
    let timer;
    const update = () => {
      clearTimeout(timer);
      const now = new Date();
      const current = businessDate(now);
      setDay(current);
      // PKT is UTC+05:00. Recheck just after its next calendar midnight.
      const midnight = Date.parse(`${current}T00:00:00+05:00`) + 86_400_000;
      timer = setTimeout(update, Math.max(50, midnight - now.getTime() + 10));
    };
    update();
    window.addEventListener("focus", update);
    document.addEventListener("visibilitychange", update);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("focus", update);
      document.removeEventListener("visibilitychange", update);
    };
  }, []);
  return day;
}
