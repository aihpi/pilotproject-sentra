import { Fragment, useState } from "react";
import type { EvalCase } from "@/types";
import { Badge } from "@/components/ui/badge";
import { VariantPanel } from "@/components/administration/VariantPanel";

type SortKey = "test_id" | "kategorie" | "ausgangsfrage" | "status";
type Direction = "asc" | "desc";

const COLLATOR = new Intl.Collator("de", { numeric: true, sensitivity: "base" });

// Workflow order rather than alphabetical, which would put "freigegeben"
// before "entwurf" and scatter the drafts still waiting for review.
const STATUS_RANK: Record<string, number> = {
  entwurf: 0,
  freigegeben: 1,
  zurückgezogen: 2,
};

function statusOf(entry: EvalCase): string {
  if (entry.zurueckgezogen_at !== null) return "zurückgezogen";
  return entry.versions[entry.versions.length - 1]?.status ?? "";
}

function compare(a: EvalCase, b: EvalCase, key: SortKey): number {
  switch (key) {
    case "status":
      return (STATUS_RANK[statusOf(a)] ?? 99) - (STATUS_RANK[statusOf(b)] ?? 99);
    case "ausgangsfrage":
      return COLLATOR.compare(
        a.versions[a.versions.length - 1]?.ausgangsfrage ?? "",
        b.versions[b.versions.length - 1]?.ausgangsfrage ?? "",
      );
    default:
      // Numeric collation, so TF-WI-010 follows TF-WI-009 rather than TF-WI-001.
      return COLLATOR.compare(a[key], b[key]);
  }
}

/** Sorted by the chosen column, ties broken by Test-ID so the order is stable. */
function sortCases(cases: EvalCase[], key: SortKey, direction: Direction): EvalCase[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...cases].sort(
    (a, b) => sign * (compare(a, b, key) || compare(a, b, "test_id")),
  );
}

function SortHeader({
  label,
  column,
  sort,
  onSort,
}: {
  label: string;
  column: SortKey;
  sort: { key: SortKey; direction: Direction };
  onSort: (column: SortKey) => void;
}) {
  const active = sort.key === column;
  return (
    <th
      className="px-3 py-2 font-medium"
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(column)}
        className="inline-flex items-center gap-1 hover:underline"
      >
        {label}
        <span aria-hidden className={active ? "" : "opacity-30"}>
          {active && sort.direction === "desc" ? "▼" : "▲"}
        </span>
      </button>
    </th>
  );
}

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
  approver = "",
}: {
  cases: EvalCase[];
  /** Who approves a variant, recorded with it. The signed-in user. */
  approver?: string;
  busy: boolean;
  onCreate: () => void;
  onEdit: (testId: string) => void;
  onApprove: (testId: string) => void;
  onWithdraw: (testId: string) => void;
}) {
  const [sort, setSort] = useState<{ key: SortKey; direction: Direction }>({
    key: "test_id",
    direction: "asc",
  });

  function onSort(column: SortKey) {
    setSort((current) =>
      current.key === column
        ? { key: column, direction: current.direction === "asc" ? "desc" : "asc" }
        : { key: column, direction: "asc" },
    );
  }

  const sorted = sortCases(cases, sort.key, sort.direction);
  // One open at a time: each panel talks to the judge model, and a table full
  // of open editors is hard to read.
  const [variantsOpen, setVariantsOpen] = useState<string | null>(null);

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
                <SortHeader label="Test-ID" column="test_id" sort={sort} onSort={onSort} />
                <SortHeader label="Kategorie" column="kategorie" sort={sort} onSort={onSort} />
                <SortHeader
                  label="Ausgangsfrage"
                  column="ausgangsfrage"
                  sort={sort}
                  onSort={onSort}
                />
                <SortHeader label="Status" column="status" sort={sort} onSort={onSort} />
                <th className="px-3 py-2 font-medium">Version</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((entry) => {
                const latest = entry.versions[entry.versions.length - 1];
                const withdrawn = entry.zurueckgezogen_at !== null;
                const approved = latest?.status === "freigegeben";
                const blockers = entry.freigabe_hindernisse ?? [];

                return (
                  <Fragment key={entry.test_id}>
                    <tr className="border-t">
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
                        {!approved && !withdrawn && blockers.length > 0 && (
                          <ul
                            aria-label="Vor der Freigabe fehlt"
                            className="mt-1 list-inside list-disc text-amber-700 dark:text-amber-400"
                          >
                            {blockers.map((blocker) => (
                              <li key={blocker}>{blocker}</li>
                            ))}
                          </ul>
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
                                disabled={busy || blockers.length > 0}
                                className="rounded-md border px-2 py-1 disabled:opacity-50"
                                title={
                                  blockers.length > 0
                                    ? `Noch nicht freigebbar: ${blockers.join("; ")}`
                                    : undefined
                                }
                              >
                                Freigeben
                              </button>
                            )}
                            {approved && (
                              <button
                                type="button"
                                onClick={() =>
                                  setVariantsOpen((open) =>
                                    open === entry.test_id ? null : entry.test_id,
                                  )
                                }
                                aria-expanded={variantsOpen === entry.test_id}
                                className="rounded-md border px-2 py-1"
                              >
                                Varianten
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
                    {variantsOpen === entry.test_id && (
                      <tr>
                        <td colSpan={6} className="px-3 pb-3">
                          <VariantPanel testId={entry.test_id} approver={approver} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
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
