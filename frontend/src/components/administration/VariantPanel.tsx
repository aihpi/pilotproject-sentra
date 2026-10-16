import { useEffect, useState } from "react";
import type { EvalVariant } from "@/types";
import {
  approveVariant,
  editVariant,
  fetchVariants,
  proposeVariants,
} from "@/lib/evalApi";
import { Badge } from "@/components/ui/badge";

const STIL_LABEL: Record<string, string> = {
  umgangssprachlich: "Umgangssprachlich",
  fachsprachlich: "Fachsprachlich",
  verkuerzt: "Verkürzt",
};

/** The three rewordings of one case's question (4.2, #265).
 *
 *  Proposed by the judge model, never by SENTRA's own model, and only counted
 *  once a person has read each one and approved it, because a variant that
 *  quietly asks something else does not measure robustness. So every proposal
 *  can be corrected before it is approved, and an approved one is shown as
 *  frozen: a round may already have measured against it.
 *
 *  The approver is whoever is signed in. An approval needs an owner, and
 *  asking somebody to type their own name is asking for a different one. */
export function VariantPanel({
  testId,
  approver,
}: {
  testId: string;
  approver: string;
}) {
  const [variants, setVariants] = useState<EvalVariant[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchVariants(testId).then(setVariants, (e: Error) => setError(e.message));
  }, [testId]);

  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function replace(updated: EvalVariant) {
    setVariants((current) =>
      current.map((v) => (v.stil === updated.stil ? updated : v)),
    );
    setDrafts((current) => {
      const rest = { ...current };
      delete rest[updated.stil];
      return rest;
    });
  }

  const allApproved =
    variants.length > 0 && variants.every((v) => v.status === "freigegeben");

  return (
    <div className="space-y-2 rounded-md border bg-muted/20 p-3">
      <div className="flex items-center gap-3">
        <span className="text-xs font-semibold">Varianten (4.2)</span>
        {!allApproved && (
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                setVariants(await proposeVariants(testId));
                setDrafts({});
              })
            }
            className="rounded-md border px-2 py-1 text-xs disabled:opacity-50"
          >
            {variants.length === 0 ? "Varianten vorschlagen" : "Neu vorschlagen"}
          </button>
        )}
        {busy && <span className="text-xs text-muted-foreground">…</span>}
      </div>

      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}

      {variants.length === 0 && !error && (
        <p className="text-xs text-muted-foreground">
          Noch keine Varianten. Vorgeschlagen werden sie vom Prüfmodell, nicht
          von SENTRA, und erst nach Freigabe in einer Runde gefragt.
        </p>
      )}

      <ul className="space-y-2">
        {variants.map((variant) => {
          const approved = variant.status === "freigegeben";
          const draft = drafts[variant.stil];
          const changed = draft !== undefined && draft !== variant.wortlaut;
          const label = STIL_LABEL[variant.stil] ?? variant.stil;

          return (
            <li key={variant.stil} className="space-y-1 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-medium">{label}</span>
                {approved ? (
                  <Badge variant="secondary">
                    freigegeben von {variant.freigegeben_durch}
                  </Badge>
                ) : (
                  <Badge variant="outline">vorgeschlagen</Badge>
                )}
              </div>
              {approved ? (
                <p className="text-muted-foreground">{variant.wortlaut}</p>
              ) : (
                <div className="flex items-start gap-2">
                  <textarea
                    aria-label={`Variante ${label}`}
                    value={draft ?? variant.wortlaut}
                    onChange={(e) =>
                      setDrafts((d) => ({ ...d, [variant.stil]: e.target.value }))
                    }
                    rows={2}
                    className="flex-1 rounded-md border bg-background px-2 py-1"
                  />
                  {changed ? (
                    <button
                      type="button"
                      disabled={busy || !draft.trim()}
                      onClick={() =>
                        void act(async () =>
                          replace(await editVariant(testId, variant.stil, draft)),
                        )
                      }
                      className="rounded-md border px-2 py-1 disabled:opacity-50"
                    >
                      Speichern
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void act(async () =>
                          replace(await approveVariant(testId, variant.stil, approver)),
                        )
                      }
                      className="rounded-md border px-2 py-1 disabled:opacity-50"
                      title="Nur freigeben, was inhaltlich eindeutig dasselbe fragt."
                    >
                      Freigeben
                    </button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
