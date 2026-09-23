import { useCallback, useEffect, useState } from "react";
import type { SentraUser, Session } from "@/types";
import { createUser, deleteUser, fetchUsers, updateUser } from "@/lib/users";
import { ROLES } from "@/lib/session";
import { Badge } from "@/components/ui/badge";

/** Who can sign in, and with what role.
 *
 *  Before this, adding a colleague was a deployment: hash a password on a
 *  developer's machine, edit a sealed secret, restart. Nobody does that for the
 *  third reviewer, so the pilot ends up sharing logins — which destroys the one
 *  thing the login was for, an author on a verdict.
 *
 *  Two kinds of account are listed and only one is editable. A configured user
 *  lives in `SENTRA_USERS` and exists so the first admin can sign in before
 *  anybody could have created one; it cannot be changed from here, and hiding
 *  it would leave an admin wondering why a name they never created can log in.
 *
 *  The refusals that matter — the last administrator, and yourself — come from
 *  the backend, which is where the rule belongs. This disables the buttons as
 *  well, because a button that always answers 409 is a worse way to learn a
 *  rule than a button that is visibly not available. */
export function UserPane({ session }: { session: Session | null }) {
  const [users, setUsers] = useState<SentraUser[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [role, setRole] = useState<string>("leser");
  const [password, setPassword] = useState("");

  const load = useCallback(() => {
    fetchUsers()
      .then(setUsers)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  async function act(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const admins = users.filter((u) => u.rolle === "admin");

  /** Why a row cannot be changed, or null if it can.
   *
   *  The same two rules the backend enforces, stated here so the reason is
   *  visible before the click rather than as a 409 afterwards. */
  function blocked(user: SentraUser): string | null {
    if (user.quelle !== "Datenbank")
      return "In SENTRA_USERS konfiguriert, hier nicht änderbar.";
    if (session && user.benutzername === session.benutzername)
      return "Das eigene Konto.";
    if (user.rolle === "admin" && admins.length <= 1)
      return "Letzter Administrator.";
    return null;
  }

  return (
    <section className="space-y-3">
      <form
        className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void act(async () => {
            await createUser(name.trim(), role, password);
            setName("");
            setPassword("");
          });
        }}
      >
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Benutzername</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-44 rounded-md border bg-background px-2 py-1 text-xs"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Rolle</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-32 rounded-md border bg-background px-2 py-1 text-xs"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Passwort</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            className="w-48 rounded-md border bg-background px-2 py-1 text-xs"
          />
        </label>

        <button
          type="submit"
          disabled={busy || !name.trim() || !password}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          Benutzer anlegen
        </button>
      </form>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
        >
          {error}
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/40 text-left">
            <tr>
              <th className="px-3 py-2 font-medium">Benutzername</th>
              <th className="px-3 py-2 font-medium">Rolle</th>
              <th className="px-3 py-2 font-medium">Herkunft</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const why = blocked(user);
              return (
                <tr key={user.benutzername} className="border-t">
                  <td className="px-3 py-2 font-medium">{user.benutzername}</td>
                  <td className="px-3 py-2">
                    <select
                      value={user.rolle}
                      disabled={busy || why !== null}
                      aria-label={`Rolle von ${user.benutzername}`}
                      onChange={(e) =>
                        void act(() =>
                          updateUser(user.benutzername, {
                            rolle: e.target.value,
                          }),
                        )
                      }
                      className="rounded-md border bg-background px-2 py-1 text-xs disabled:opacity-50"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <Badge
                      variant={
                        user.quelle === "Datenbank" ? "secondary" : "outline"
                      }
                    >
                      {user.quelle}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {why ? (
                      <span className="text-muted-foreground">{why}</span>
                    ) : (
                      <span className="flex justify-end gap-1">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            const neu = window.prompt(
                              `Neues Passwort für ${user.benutzername}`,
                            );
                            if (neu)
                              void act(() =>
                                updateUser(user.benutzername, {
                                  passwort: neu,
                                }),
                              );
                          }}
                          className="rounded-md border px-2 py-1 disabled:opacity-50"
                        >
                          Passwort setzen
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void act(() => deleteUser(user.benutzername))
                          }
                          className="rounded-md border px-2 py-1 text-destructive disabled:opacity-50"
                        >
                          Löschen
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted-foreground">
        Der letzte Administrator und das eigene Konto lassen sich nicht löschen
        oder herabstufen — eine Installation, die niemand mehr verwalten kann,
        ist nur noch über die Datenbank zu reparieren. Konfigurierte Benutzer
        stammen aus <code>SENTRA_USERS</code> und existieren, damit sich
        überhaupt jemand anmelden kann, bevor es hier Konten gibt.
      </p>
    </section>
  );
}
