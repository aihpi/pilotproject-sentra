import { useState } from "react";
import type { Session } from "@/types";
import { login } from "@/lib/session";

/** Signing in.
 *
 *  Shown only when the installation can actually authenticate somebody. A
 *  deployment with no users configured is open by design, and a sign-in box in
 *  front of it would be a lie — there would be nothing to sign in as.
 *
 *  The failure message comes from the server unchanged. It says the same thing
 *  for a wrong password and for a name that does not exist, deliberately, and
 *  improving on that here by guessing which one it was would undo the point. */
export function LoginScreen({
  onSignedIn,
}: {
  onSignedIn: (session: Session) => void;
}) {
  const [benutzername, setBenutzername] = useState("");
  const [passwort, setPasswort] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await login(benutzername, passwort));
    } catch (e) {
      setError((e as Error).message);
      setPasswort("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-sm flex-col justify-center p-6">
      <form
        onSubmit={submit}
        className="space-y-4 rounded-lg border bg-card p-6"
      >
        <div>
          <h2 className="text-lg font-semibold">Anmeldung</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            SENTRA ist ein Prototyp. Die Anmeldung ordnet Bewertungen einer
            Person zu und entscheidet, welche Bereiche sichtbar sind.
          </p>
        </div>

        <label className="block space-y-1">
          <span className="text-xs font-medium">Benutzername</span>
          <input
            value={benutzername}
            onChange={(e) => setBenutzername(e.target.value)}
            autoComplete="username"
            autoFocus
            className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
          />
        </label>

        <label className="block space-y-1">
          <span className="text-xs font-medium">Passwort</span>
          <input
            type="password"
            value={passwort}
            onChange={(e) => setPasswort(e.target.value)}
            autoComplete="current-password"
            className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
          />
        </label>

        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || !benutzername || !passwort}
          className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {busy ? "Wird geprüft …" : "Anmelden"}
        </button>
      </form>
    </div>
  );
}
