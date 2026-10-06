import type { DocumentInfo, VolumeFile } from "@/types";

/** Where the documents volume and the index disagree.
 *
 *  Each group has a different cause and a different remedy, which is why they
 *  are not one "missing" list: a PDF waiting for ingestion needs *Dokumente
 *  einlesen*, a withdrawn one must not be read in again, a .docx never will be,
 *  and an indexed document with no file is the orphan problem of #140.
 *  Telling these apart used to mean mounting the volume from a throwaway Job. */
export function VolumeComparison({
  files,
  documents,
}: {
  files: VolumeFile[];
  documents: DocumentInfo[];
}) {
  const indexed = new Set(documents.map((d) => d.source_file));
  const onVolume = new Set(files.map((f) => f.name));

  const notIndexed = files.filter((f) => !indexed.has(f.name));
  const groups: Group[] = [
    {
      title: "Bereit zum Einlesen",
      hint: "PDFs auf dem Volume, die noch nicht im Index sind. „Dokumente einlesen“ nimmt sie auf.",
      names: notIndexed.filter((f) => f.indexable && f.withdrawn !== true).map((f) => f.name),
    },
    {
      title: "Zurückgezogen",
      hint: "Die Datei bleibt erhalten, wird aber nicht wieder eingelesen.",
      names: notIndexed.filter((f) => f.indexable && f.withdrawn === true).map((f) => f.name),
    },
    {
      title: "Werden nicht eingelesen",
      hint: "Nur PDFs werden indiziert. Diese Dateien liegen auf dem Volume, sind aber nicht durchsuchbar.",
      names: notIndexed.filter((f) => !f.indexable).map((f) => f.name),
    },
    {
      title: "Im Index ohne Datei",
      hint: "Durchsuchbar und zitierbar, obwohl keine Datei mehr dahintersteht.",
      names: documents.filter((d) => !onVolume.has(d.source_file)).map((d) => d.source_file),
    },
  ];
  const registryUnknown = files.some((f) => f.withdrawn === null);

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {files.length} Dateien auf dem Volume, {documents.length} Dokumente im Index.
      </p>

      {registryUnknown && (
        <p className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
          Die Registry ist nicht erreichbar. Zurückgezogene Dokumente können
          nicht erkannt werden und erscheinen unter „Bereit zum Einlesen“.
        </p>
      )}

      {groups.every((g) => g.names.length === 0) ? (
        <p className="text-xs text-muted-foreground">Volume und Index stimmen überein.</p>
      ) : (
        <ul className="divide-y rounded-md border">
          {groups
            .filter((g) => g.names.length > 0)
            .map((g) => (
              <li key={g.title} className="px-3 py-2 text-xs">
                <details>
                  <summary className="cursor-pointer">
                    <span className="font-medium">{g.title}</span>{" "}
                    <span className="tabular-nums text-muted-foreground">({g.names.length})</span>
                  </summary>
                  <p className="mt-1 text-muted-foreground">{g.hint}</p>
                  <ul className="mt-1 max-h-48 space-y-0.5 overflow-y-auto">
                    {g.names.map((name) => (
                      <li key={name} className="truncate">
                        {name}
                      </li>
                    ))}
                  </ul>
                </details>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

type Group = { title: string; hint: string; names: string[] };
