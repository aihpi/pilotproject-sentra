import type { Agreement } from "@/types";

/** Stufe 1 against a human — section 6's headline measurement.
 *
 *  The one thing this component exists to get right: **a rate of zero and no
 *  rate at all are different facts and must not look alike.** Zero means the
 *  checks and the reviewers agreed on everything they both looked at. Null
 *  means nobody has looked. Rendering null as "0 %" would report perfect
 *  agreement from a round nobody has reviewed, which is the most flattering
 *  possible way to be wrong about the number that calibrates the Prüfschwelle.
 *
 *  So the rate is only ever shown when it exists, and its absence is stated
 *  rather than filled in. */
export function AgreementCard({ agreement }: { agreement: Agreement }) {
  const { einig, zu_streng, zu_grosszuegig, nicht_bewertet, abweichungsquote } = agreement;
  const bewertet = einig + zu_streng + zu_grosszuegig;

  return (
    <section className="rounded-lg border bg-card p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Abweichung Stufe 1 ↔ manuelle Prüfung
      </h3>

      {abweichungsquote === null ? (
        <p className="mt-2 text-sm text-muted-foreground">
          Noch keine Quote — in dieser Runde wurde noch kein Testfall manuell bewertet.
          {nicht_bewertet > 0 && ` ${nicht_bewertet} offen.`}
        </p>
      ) : (
        <>
          {/* Labelled, because the number and its unit are separate nodes for
              styling and would otherwise be read out as two things. It also
              gives the one assertion that matters something unambiguous to
              find: a bare "0" also appears in the counters below. */}
          <p
            className="mt-1 text-3xl font-semibold tabular-nums"
            aria-label={`Abweichungsquote ${(abweichungsquote * 100).toFixed(0)} Prozent`}
          >
            {(abweichungsquote * 100).toFixed(0)}
            <span className="text-lg font-normal text-muted-foreground"> %</span>
          </p>
          <p className="text-xs text-muted-foreground">
            {bewertet === 1
              ? "aus 1 bewertetem Testfall"
              : `aus ${bewertet} bewerteten Testfällen`}
            {nicht_bewertet > 0 && `, ${nicht_bewertet} offen`}
          </p>
        </>
      )}

      <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded-md bg-muted/40 p-2">
          <dt className="text-muted-foreground">einig</dt>
          <dd className="text-base font-semibold tabular-nums">{einig}</dd>
        </div>
        <div className="rounded-md bg-muted/40 p-2">
          <dt className="text-muted-foreground" title="Die Prüfung schlug an, die Bewertung nicht.">
            zu streng
          </dt>
          <dd className="text-base font-semibold tabular-nums">{zu_streng}</dd>
        </div>
        <div className="rounded-md bg-muted/40 p-2">
          <dt
            className="text-muted-foreground"
            title="Die Bewertung fand einen Befund, den die Prüfung nicht sah."
          >
            zu großzügig
          </dt>
          <dd className="text-base font-semibold tabular-nums">{zu_grosszuegig}</dd>
        </div>
      </dl>

      <p className="mt-2 text-xs text-muted-foreground">
        Die beiden Richtungen werden nie zusammengefasst: zu streng kostet Prüfzeit, zu großzügig
        lässt einen Befund durch. Aus dieser Quote wird die Prüfschwelle kalibriert.
      </p>
    </section>
  );
}
