import { useEffect, useState } from "react";

import { fetchActivePolicy } from "../api/client.js";

// One request per page load; every component asking shares it.
let pending = null;

/**
 * The credit policy in force now (`GET /policy/active`), for drawing anything
 * about the present: an empty dial before an assessment, for instance. A stored
 * application is drawn with its own policy snapshot instead.
 */
export function useActivePolicy() {
  const [policy, setPolicy] = useState(null);

  useEffect(() => {
    let alive = true;
    pending ??= fetchActivePolicy().catch((error) => {
      pending = null; // retry on the next mount
      throw error;
    });
    pending.then((value) => alive && setPolicy(value)).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  return policy;
}

/** Forget the cached policy, e.g. after an admin activates another version. */
export function refreshActivePolicy() {
  pending = null;
}
