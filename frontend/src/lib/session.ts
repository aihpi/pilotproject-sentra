import type { Session } from "@/types";
import { API_BASE, request } from "@/lib/api";

/** The prototype login, from the browser's side.
 *
 *  Roles are ordered rather than a set of permissions, so "at least a
 *  reviewer" is one comparison instead of a list to keep in step with the
 *  backend's. The order here has to match `sentra.api.identity.ROLES`; there is
 *  a test that says so in words, since nothing can enforce it across two
 *  languages. */
export const ROLES = ["leser", "pruefer", "admin"] as const;

export function atLeast(role: string, minimum: string): boolean {
  const have = ROLES.indexOf(role as (typeof ROLES)[number]);
  const need = ROLES.indexOf(minimum as (typeof ROLES)[number]);
  // An unknown role grants nothing. It means the backend has roles this build
  // does not know about, and guessing upwards would be the wrong way to be
  // wrong.
  return have >= 0 && need >= 0 && have >= need;
}

/** The current session, or null when there is none.
 *
 *  A 401 here is the ordinary answer for "not signed in", not a failure, so it
 *  does not go through `request` — that turns a 401 into a thrown Error with a
 *  message meant for a user, and this is a question rather than an attempt. */
export async function fetchSession(): Promise<Session | null> {
  try {
    const response = await fetch(`${API_BASE}/me`, { credentials: "include" });
    if (response.status === 401) return null;
    if (!response.ok) return null;
    return (await response.json()) as Session;
  } catch {
    return null;
  }
}

/** Whether this installation can authenticate anybody at all.
 *
 *  A deployment with no users configured is open by design, and putting a
 *  sign-in box in front of it would be a lie — there would be nothing to sign
 *  in as. `/api/health` reports it, so the UI asks rather than assumes. */
export async function loginConfigured(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/health`, {
      credentials: "include",
    });
    if (!response.ok) return false;
    const body = (await response.json()) as { login?: string };
    return body.login === "eingerichtet";
  } catch {
    // Unreachable backend: not the moment to demand a password. The rest of
    // the UI will show its own error for the same cause.
    return false;
  }
}

export function login(
  benutzername: string,
  passwort: string,
): Promise<Session> {
  return request("/login", {
    method: "POST",
    body: { benutzername, passwort },
    label: "Die Anmeldung ist fehlgeschlagen",
    statusMessages: {
      503: "Für diese Installation ist keine Anmeldung eingerichtet.",
    },
  });
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/logout`, { method: "POST", credentials: "include" });
}
