import { useEffect, useState } from "react";
import type { Agreement, Sheet, Trend, TriageSummary, Verdict } from "@/types";
import { fetchAgreement, fetchKisz, fetchSheets, fetchTrend, fetchTriage } from "@/lib/evalApi";
import { AgreementCard } from "@/components/evaluation/AgreementCard";
import { SheetCard } from "@/components/evaluation/SheetCard";
import { TriagePane } from "@/components/evaluation/TriagePane";
import { Badge } from "@/components/ui/badge";

/** What a round concluded.
 *
 *  The counterpart to the review queue: the queue is what still has to be
 *  looked at, this is what came out. Everything here is derived from stored
 *  rows, so it is reproducible — re-reading a finished round gives the same
 *  answer next month as it did on the day.
 *
 *  Loaded in one go rather than per panel. They are five reads of the same
 *  round and a partial view of a round is worse than a spinner: a triage split
 *  beside a stale disagreement rate invites conclusions about a round that
 *  never existed. */
export function ResultsView({ runId }: { runId: string }) {
  const [triage, setTriage] = useState<TriageSummary | null>(null);
  const [agreement, setAgreement] = useState<Agreement | null>(null);
  const [sheets, setSheets] = useState<Sheet[]>([]);
  const [kisz, setKisz] = useState<Verdict[]>([]);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Nothing is reset here, and the effect only writes state asynchronously.
  // Switching rounds remounts this component through its `key` — the same
  // device VerdictForm uses — so the reset is the mount rather than a
  // synchronous setState the lint rule rightly objects to.
  useEffect(() => {
    let current = true;
    Promise.all([
      fetchTriage(runId),
      fetchAgreement(runId),
      fetchSheets(runId),
      fetchKisz(runId),
      fetchTrend(),
    ])
      .then(([loadedTriage, loadedAgreement, loadedSheets, loadedKisz, loadedTrend]) => {
        if (!current) return;
        setTriage(loadedTriage);
        setAgreement(loadedAgreement);
        setSheets(loadedSheets);
        setKisz(loadedKisz);
        setTrend(loadedTrend);
      })
      .catch((e: Error) => current && setError(e.message))
      .finally(() => current && setLoading(false));
    return () => {
      current = false;
    };
  }, [runId]);

  if (error) {
    return (
      <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        {error}
      </p>
    );
  }

  if (loading || !triage || !agreement || !trend) {
    return <p className="text-sm text-muted-foreground">Ergebnisse werden geladen …</p>;
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <AgreementCard agreement={agreement} />
        <TriagePane triage={triage} />
      </div>

      {kisz.length > 0 && (
        <section className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-destructive">
            An KISZ zu melden
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Schweregrad 3 und 4 verlassen den WD-Prozess und werden separat gemeldet.
          </p>
          <ul className="mt-2 space-y-1">
            {kisz.map((verdict) => (
              <li key={verdict.id} className="flex items-center gap-2 text-xs">
                <Badge variant="destructive">Schweregrad {verdict.schweregrad}</Badge>
                <span className="text-muted-foreground">{verdict.anmerkung || "—"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Dokumentationsbögen (Phase 4)
        </h3>
        {sheets.length === 0 ? (
          <p className="text-sm text-muted-foreground">Keine Testfälle in dieser Runde.</p>
        ) : (
          sheets.map((sheet) => <SheetCard key={sheet.test_id} sheet={sheet} />)
        )}
      </section>

      <TrendPane trend={trend} />
    </div>
  );
}

/** The monthly Trendauswertung, across every round rather than this one.
 *
 *  Section 6's "wo häufen sich Fußnotenfehler". The counts are per case, not
 *  per answer, so a round run with three repeats does not report three times
 *  the findings — see #136, where it did. */
function TrendPane({ trend }: { trend: Trend }) {
  const befunde = Object.entries(trend.haeufigste_befunde);
  const schweregrade = Object.entries(trend.schweregrade);

  return (
    <section className="rounded-lg border bg-card p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Trend über alle Runden
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        {trend.runden} {trend.runden === 1 ? "Runde" : "Runden"}, {trend.faelle}{" "}
        {trend.faelle === 1 ? "Testfall" : "Testfälle"}
        {trend.kisz_meldungen > 0 && `, ${trend.kisz_meldungen} an KISZ gemeldet`}
      </p>

      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div>
          <h4 className="text-xs font-medium">Häufigste Befunde</h4>
          {befunde.length === 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">Keine auffälligen Prüfungen.</p>
          ) : (
            <ul className="mt-1 space-y-1">
              {befunde.map(([pruefung, count]) => (
                <li key={pruefung} className="flex justify-between gap-2 text-xs">
                  <span>{pruefung}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {count} {count === 1 ? "Fall" : "Fälle"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h4 className="text-xs font-medium">Schweregrade</h4>
          {schweregrade.length === 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">Noch nichts bewertet.</p>
          ) : (
            <ul className="mt-1 space-y-1">
              {schweregrade.map(([grad, count]) => (
                <li key={grad} className="flex justify-between gap-2 text-xs">
                  <span>Grad {grad}</span>
                  <span className="tabular-nums text-muted-foreground">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
