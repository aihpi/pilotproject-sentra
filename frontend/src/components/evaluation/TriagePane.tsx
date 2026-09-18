import type { TriageSummary } from "@/types";

/** How the round split across the Stufen.
 *
 *  `grenzfaelle` is not a fourth bucket and is shown apart from the other
 *  three for that reason: a Grenzfall reaches a human whatever the checks
 *  said, so it is already counted in Stufe 2. Adding the four together would
 *  overcount, and putting them in one row invites exactly that. */
export function TriagePane({ triage }: { triage: TriageSummary }) {
  const { gesamt, stufe_2, stufe_3, grenzfaelle, unauffaellig } = triage;

  const buckets = [
    { label: "Stufe 2", value: stufe_2, hint: "auffällig markiert, geht an eine Person" },
    { label: "Stufe 3", value: stufe_3, hint: "Stichprobe aus den unauffälligen Fällen" },
    { label: "unauffällig", value: unauffaellig, hint: "keine Prüfung hat angeschlagen" },
  ];

  return (
    <section className="rounded-lg border bg-card p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Triage — {gesamt} {gesamt === 1 ? "Testfall" : "Testfälle"}
      </h3>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
        {buckets.map((bucket) => (
          <div key={bucket.label} className="rounded-md bg-muted/40 p-2" title={bucket.hint}>
            <dt className="text-muted-foreground">{bucket.label}</dt>
            <dd className="text-base font-semibold tabular-nums">{bucket.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">
        davon {grenzfaelle} {grenzfaelle === 1 ? "Grenzfall" : "Grenzfälle"} — die gehen immer an
        eine Person, unabhängig davon, was die Prüfungen gesagt haben, und sind oben bereits
        mitgezählt.
      </p>
    </section>
  );
}
