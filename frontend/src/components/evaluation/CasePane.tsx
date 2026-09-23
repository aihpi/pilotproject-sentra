import type { QueueEntry } from "@/types";
import { Badge } from "@/components/ui/badge";

/** The test case, read only, beside the answer.
 *
 *  It is the yardstick — the expected answer and the two reference sources are
 *  what the answer is being measured against — so it stays on screen and
 *  cannot be edited from here. The Vorlage requires the expectation to be
 *  written before SENTRA is tested; a reviewer looking at a disappointing
 *  answer is precisely the person who should not be able to adjust it. The
 *  harness enforces that too: an approved version is immutable. */
export function CasePane({ entry }: { entry: QueueEntry }) {
  return (
    <aside className="space-y-4 rounded-lg border bg-muted/30 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="font-mono">
          {entry.test_id}
        </Badge>
        <Badge variant="secondary">{entry.kategorie}</Badge>
        {entry.grenzfall && (
          <Badge variant="destructive" title="Wird nie automatisch vorgefiltert (4.4)">
            Grenzfall
          </Badge>
        )}
      </div>

      <Field label="Ausgangsfrage">{entry.ausgangsfrage}</Field>
      <Field label="Erwartete Antwort">
        {entry.erwartete_antwort || <Missing />}
      </Field>
      <Field label="Referenzquelle (korrekt)">
        {entry.referenz_korrekt || <Missing />}
      </Field>
      <Field label="Referenzquelle (veraltet/falsch)">
        {entry.referenz_falsch || <Missing />}
      </Field>

      <p className="border-t pt-3 text-[11px] text-muted-foreground">
        Gefunden über: {entry.gefunden_ueber}
      </p>
    </aside>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </h4>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{children}</p>
    </div>
  );
}

/** An empty reference field is worth showing as absent rather than as blank:
 *  the source checks report "nicht prüfbar" for it, and a reviewer should know
 *  that is why rather than wondering what the check missed. */
function Missing() {
  return <span className="italic text-muted-foreground">nicht hinterlegt</span>;
}
