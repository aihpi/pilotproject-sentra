import { Fragment, useState } from "react";
import type { EvalCase, LabelValues } from "@/types";
import { Badge } from "@/components/ui/badge";
import { VariantPanel } from "@/components/administration/VariantPanel";
import { LabelPanel } from "@/components/administration/LabelPanel";

type SortKey = "nummer" | "tag" | "kategorie" | "testart" | "ausgangsfrage" | "status";

const FILTERS = [
  { key: "kategorie", label: "Bereich" },
  { key: "testart", label: "Testart" },
  { key: "frageform", label: "Frageform" },
  { key: "herkunft", label: "Herkunft" },
  { key: "status", label: "Status" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

const NO_LABELS: LabelValues = { kategorie: [], testart: [], frageform: [], herkunft: [] };
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
    case "nummer":
      return a.nummer - b.nummer;
    case "testart":
      return COLLATOR.compare(a.testart ?? "", b.testart ?? "");
    default:
      return COLLATOR.compare(a[key], b[key]);
  }
}

/** Sorted by the chosen column, ties broken by number so the order is stable. */
function sortCases(cases: EvalCase[], key: SortKey, direction: Direction): EvalCase[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...cases].sort(
    (a, b) => sign * (compare(a, b, key) || compare(a, b, "nummer")),
  );
}

/** The value a filter compares, empty where the case has none. */
function filterValue(entry: EvalCase, key: FilterKey): string {
  return key === "status" ? statusOf(entry) : (entry[key] ?? "");
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
 *  Withdrawal is not deletion and the wording says so. The number stays
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
  offered = NO_LABELS,
  onLabelsChanged = () => {},
}: {
  cases: EvalCase[];
  /** The values to suggest when editing labels (#288). */
  offered?: LabelValues;
  /** A case's labels or tag were saved, so the list is stale. */
  onLabelsChanged?: () => void;
  /** Who approves a variant, recorded with it. The signed-in user. */
  approver?: string;
  busy: boolean;
  onCreate: () => void;
  onEdit: (nummer: number) => void;
  onApprove: (nummer: number) => void;
  onWithdraw: (nummer: number) => void;
}) {
  const [sort, setSort] = useState<{ key: SortKey; direction: Direction }>({
    key: "nummer",
    direction: "asc",
  });

  function onSort(column: SortKey) {
    setSort((current) =>
      current.key === column
        ? { key: column, direction: current.direction === "asc" ? "desc" : "asc" }
        : { key: column, direction: "asc" },
    );
  }

  // "" means no filter on that dimension.
  const [filters, setFilters] = useState<Record<FilterKey, string>>({
    kategorie: "",
    testart: "",
    frageform: "",
    herkunft: "",
    status: "",
  });
  const shown = cases.filter((entry) =>
    FILTERS.every(({ key }) => !filters[key] || filterValue(entry, key) === filters[key]),
  );
  const sorted = sortCases(shown, sort.key, sort.direction);
  // One panel open at a time: a table full of open editors is hard to read.
  const [panel, setPanel] = useState<{ nummer: number; what: "varianten" | "labels" } | null>(
    null,
  );
  const toggle = (nummer: number, what: "varianten" | "labels") =>
    setPanel((open) =>
      open?.nummer === nummer && open.what === what ? null : { nummer, what },
    );

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Testfälle ({shown.length === cases.length ? cases.length : `${shown.length} von ${cases.length}`})
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

      {cases.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {FILTERS.map(({ key, label }) => {
            const values = [...new Set(cases.map((c) => filterValue(c, key)))]
              .filter(Boolean)
              .sort((a, b) => COLLATOR.compare(a, b));
            return (
              <select
                key={key}
                aria-label={`Filter ${label}`}
                value={filters[key]}
                onChange={(e) => setFilters((f) => ({ ...f, [key]: e.target.value }))}
                className="rounded-md border bg-background px-2 py-1"
              >
                <option value="">{label}: alle</option>
                {values.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            );
          })}
        </div>
      )}

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
                <SortHeader label="Nr." column="nummer" sort={sort} onSort={onSort} />
                <SortHeader label="Tag" column="tag" sort={sort} onSort={onSort} />
                <SortHeader label="Bereich" column="kategorie" sort={sort} onSort={onSort} />
                <SortHeader label="Testart" column="testart" sort={sort} onSort={onSort} />
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
                  <Fragment key={entry.nummer}>
                    <tr className="border-t">
                      <td className="whitespace-nowrap px-3 py-2 font-medium">
                        {entry.nummer}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono">
                        {entry.tag}
                      </td>
                      <td className="px-3 py-2">{entry.kategorie}</td>
                      <td className="px-3 py-2">{entry.testart || "—"}</td>
                      <td className="max-w-md px-3 py-2">
                        <span className="line-clamp-2">
                          {latest?.ausgangsfrage}
                        </span>
                        {(entry.frageform || entry.herkunft) && (
                          <span className="mt-0.5 block text-[11px] text-muted-foreground">
                            {[entry.frageform, entry.herkunft].filter(Boolean).join(" · ")}
                          </span>
                        )}
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
                            title="Die Nummer bleibt vergeben."
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
                              onClick={() => onEdit(entry.nummer)}
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
                                onClick={() => onApprove(entry.nummer)}
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
                                onClick={() => toggle(entry.nummer, "varianten")}
                                aria-expanded={
                                  panel?.nummer === entry.nummer && panel.what === "varianten"
                                }
                                className="rounded-md border px-2 py-1"
                              >
                                Varianten
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => toggle(entry.nummer, "labels")}
                              aria-expanded={
                                panel?.nummer === entry.nummer && panel.what === "labels"
                              }
                              className="rounded-md border px-2 py-1"
                              title="Tag und Labels ändern. Legt keine neue Version an."
                            >
                              Labels
                            </button>
                            <button
                              type="button"
                              onClick={() => onWithdraw(entry.nummer)}
                              disabled={busy}
                              className="rounded-md border px-2 py-1 text-destructive disabled:opacity-50"
                              title="Nimmt den Testfall aus künftigen Runden. Die Nummer bleibt vergeben und wird nie erneut verwendet."
                            >
                              Zurückziehen
                            </button>
                          </span>
                        )}
                      </td>
                    </tr>
                    {panel?.nummer === entry.nummer && (
                      <tr>
                        <td colSpan={8} className="px-3 pb-3">
                          {panel.what === "varianten" ? (
                            <VariantPanel nummer={entry.nummer} approver={approver} />
                          ) : (
                            <LabelPanel
                              key={`${entry.nummer}-${entry.tag}`}
                              entry={entry}
                              offered={offered}
                              onSaved={onLabelsChanged}
                            />
                          )}
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
        seine Nummer wird nie erneut vergeben — auch bei zurückgezogenen
        Testfällen nicht.
      </p>
    </section>
  );
}
