import type { MachineVerdicts } from "@/types";
import { Badge } from "@/components/ui/badge";

/** What the automated checks concluded — shown only after a sheet is submitted.
 *
 *  Not a collapsed panel: before submit there is nothing to collapse, because
 *  the queue does not carry machine verdicts and this component is not given
 *  any. Section 6 of the Vorlage makes the disagreement between the automatic
 *  verdict and the human one the most important number in the process, and it
 *  only measures anything if the human did not see the machine's answer first.
 *
 *  The empty state says so, because a reviewer who thinks the checks are
 *  broken will go looking for the bug. */
export function MachineVerdictPane({ verdicts }: { verdicts: MachineVerdicts | null }) {
  if (verdicts === null) {
    return (
      <section className="rounded-lg border border-dashed bg-muted/20 p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Automatikprüfung
        </h3>
        <p className="mt-2 text-xs text-muted-foreground">
          Wird erst nach dem Abschicken angezeigt. Die Abweichung zwischen automatischer und
          manueller Bewertung ist die zentrale Kennzahl des Verfahrens — sie misst nur dann
          etwas, wenn die Bewertung unabhängig entstanden ist.
        </p>
      </section>
    );
  }

  const all = [...verdicts.per_call, ...verdicts.per_group];

  return (
    <section className="space-y-2 rounded-lg border bg-card p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Automatikprüfung
      </h3>
      <ul className="space-y-1">
        {all.map((check) => (
          <li key={check.pruefung} className="flex items-center gap-2 text-xs">
            <Badge variant={check.auffaellig ? "destructive" : "secondary"}>
              {check.auffaellig ? "auffällig" : "unauffällig"}
            </Badge>
            <span className="font-medium">{check.pruefung}</span>
            <span className="text-muted-foreground">{check.ergebnis}</span>
          </li>
        ))}
        {all.length === 0 && (
          <li className="text-xs text-muted-foreground">Keine Prüfergebnisse vorhanden.</li>
        )}
      </ul>
    </section>
  );
}
