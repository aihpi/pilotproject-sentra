import type { ViewType } from "@/App";

/** The role each view is worth offering to.
 *
 *  **Offering, not permitting.** The backend refuses — see `api/auth.py` — and
 *  this only decides what is worth putting in front of somebody. A tab hidden
 *  here is still an endpoint reachable with curl, so anyone arriving looking
 *  for the access control is in the wrong file.
 *
 *  Hiding it is still worth doing: a button that answers 403 is a worse
 *  experience than a button that is not there.
 *
 *  Its own module because App may only export components — and because the
 *  mapping is a fact about the application rather than about its root. */
export const VIEW_ROLES: Record<ViewType, string> = {
  explorer: "leser",
  documents: "leser",
  evaluation: "pruefer",
  administration: "admin",
};

export const ALL_VIEWS = Object.keys(VIEW_ROLES) as ViewType[];
