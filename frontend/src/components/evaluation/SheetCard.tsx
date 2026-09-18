import type { Sheet } from "@/types";
import { Badge } from "@/components/ui/badge";
import { labelForKey, labelForVariant } from "@/components/evaluation/callLabels";

/** One Phase-4 documentation sheet.
 *
 *  Laid out as the Vorlage's sheet, with its field names kept in German. A
 *  sheet is what gets filed, and translating the vocabulary is how the sheet
 *  and the template drift apart — the same reason the harness's tables carry
 *  the German names.
 *
 *  `angewendete_techniken` lists what the round actually did rather than the
 *  full set of four. A case with no approved variants did not exercise 4.2,
 *  and a sheet claiming otherwise would be a sheet nobody should sign. */
export function SheetCard({ sheet }: { sheet: Sheet }) {
  const befunde = Object.entries(sheet.kernbefund_je_variante);

  return (
    <article className="space-y-3 rounded-lg border bg-card p-4">
      <header className="flex flex-wrap items-baseline gap-2">
        <h4 className="font-semibold">{sheet.test_id}</h4>
        <span className="text-xs text-muted-foreground">{sheet.kategorie}</span>
        <span className="text-xs text-muted-foreground">{sheet.datum}</span>
        {sheet.schweregrad !== null && (
          <Badge variant={sheet.schweregrad >= 3 ? "destructive" : "secondary"}>
            Schweregrad {sheet.schweregrad}
          </Badge>
        )}
        {sheet.tester === "" && (
          <Badge variant="outline" title="Kein Dokumentationsbogen ausgefüllt.">
            noch nicht bewertet
          </Badge>
        )}
      </header>

      <p className="text-sm">{sheet.urspruenglicher_prompt}</p>

      <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[13rem_1fr]">
        <Row label="Angewendete Techniken" value={sheet.angewendete_techniken.join(", ")} />
        <Row
          label="Geprüfte Varianten"
          value={sheet.geprüfte_varianten.map(labelForVariant).join(", ")}
        />
        <Row label="Varianten erstellt durch" value={sheet.varianten_erstellt_durch} />
        <Row label="Varianten freigegeben durch" value={sheet.varianten_freigegeben_durch} />
        <Row label="Automatisiert geprüft durch" value={sheet.automatisiert_geprueft_durch} />
        <Row label="Ergebnis Automatikprüfung" value={sheet.ergebnis_automatikpruefung} />
        <Row label="Gefunden über" value={sheet.gefunden_ueber} />
        <Row label="Manuell geprüft durch" value={sheet.manuell_geprueft_durch} />
        <Row label="Quellenprüfung 4.3a" value={sheet.quellenbewertung_4_3a} />
        <Row label="Quellenprüfung 4.3b" value={sheet.quellenbewertung_4_3b} />
        <Row label="Quellenprüfung 4.3c" value={sheet.quellenbewertung_4_3c} />
        <Row label="Reproduzierbar" value={sheet.reproduzierbar} />
      </dl>

      {befunde.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Kernbefund je Variante
          </h5>
          <ul className="mt-1 space-y-1">
            {befunde.map(([key, text]) => (
              <li key={key} className="text-xs">
                <span className="font-medium">{labelForKey(key)}: </span>
                <span className="text-muted-foreground">{text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {sheet.freitext_anmerkung && (
        <p className="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
          {sheet.freitext_anmerkung}
        </p>
      )}
    </article>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value || <span className="text-muted-foreground">—</span>}</dd>
    </>
  );
}
