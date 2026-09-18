import type { EvalCase } from "@/types";
import { Badge } from "@/components/ui/badge";

/** Every test case, and what can be done to it.
 *
 *  Which actions are offered follows the state rather than being offered
 *  always and failing:
 *
 *    a draft          can be edited and approved
 *    an approved case can be edited — which adds a version — and withdrawn
 *    a withdrawn case can do neither, and says why it is still listed
 *
 *  Withdrawal is not deletion and the wording says so. The Test-ID stays
 *  spent, "auch bei zurückgezogenen Testfällen nicht", so somebody expecting
 *  a delete would otherwise go looking for where the number went. */
export function CaseTable({
  cases,
  busy,
  onCreate,
  onEdit,
  onApprove,
  onWithdraw,
}: {
  cases: EvalCase[];
  busy: boolean;
  onCreate: () => void;
  onEdit: (testId: string) => void;
  onApprove: (testId: string) => void;
  onWithdraw: (testId: string) => void;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Testfälle ({cases.length})
        </h3>
        <button
          type="button"
          onClick={onCreate}
          disabled={busy}
          className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          Neuer Testfall
        </button>
      </div>

      {cases.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          Noch keine Testfälle. Einzeln anlegen, oder die ausgefüllte
          Erfassungsvorlage oben hochladen.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/40 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">Test-ID</th>
                <th className="px-3 py-2 font-medium">Kategorie</th>
                <th className="px-3 py-2 font-medium">Ausgangsfrage</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Version</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {cases.map((entry) => {
                const latest = entry.versions[entry.versions.length - 1];
                const withdrawn = entry.zurueckgezogen_at !== null;
                const approved = latest?.status === "freigegeben";

                return (
                  <tr key={entry.test_id} className="border-t">
                    <td className="whitespace-nowrap px-3 py-2 font-medium">
                      {entry.test_id}
                    </td>
                    <td className="px-3 py-2">{entry.kategorie}</td>
                    <td className="max-w-md px-3 py-2">
                      <span className="line-clamp-2">
                        {latest?.ausgangsfrage}
                      </span>
                      {latest?.grenzfall && (
                        <Badge variant="outline" className="mt-1">
                          Grenzfall
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {withdrawn ? (
                        <Badge
                          variant="outline"
                          title="Die Test-ID bleibt vergeben."
                        >
                          zurückgezogen
                        </Badge>
                      ) : (
                        <Badge variant={approved ? "secondary" : "outline"}>
                          {latest?.status}
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {latest?.version}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      {!withdrawn && (
                        <span className="flex justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => onEdit(entry.test_id)}
                            disabled={busy}
                            className="rounded-md border px-2 py-1 disabled:opacity-50"
                            title={
                              approved
                                ? "Legt eine neue Version an; die freigegebene bleibt unverändert."
                                : undefined
                            }
                          >
                            {approved ? "Neue Version" : "Bearbeiten"}
                          </button>
                          {!approved && (
                            <button
                              type="button"
                              onClick={() => onApprove(entry.test_id)}
                              disabled={busy}
                              className="rounded-md border px-2 py-1 disabled:opacity-50"
                            >
                              Freigeben
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => onWithdraw(entry.test_id)}
                            disabled={busy}
                            className="rounded-md border px-2 py-1 text-destructive disabled:opacity-50"
                            title="Nimmt den Testfall aus künftigen Runden. Die Test-ID bleibt vergeben und wird nie erneut verwendet."
                          >
                            Zurückziehen
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
      )}

      <p className="text-xs text-muted-foreground">
        Zurückziehen löscht nichts: der Testfall bleibt als Beleg erhalten und
        seine Test-ID wird nie erneut vergeben — auch bei zurückgezogenen
        Testfällen nicht.
      </p>
    </section>
  );
}
