export interface DocumentInfo {
  aktenzeichen: string;
  title: string;
  fachbereich_number: string;
  fachbereich: string;
  document_type: string;
  completion_date: string;
  language: string;
  source_file: string;
}

export interface FeedbackRequest {
  question: string;
  answer: string;
  rating: "positive" | "negative";
  comment?: string | null;
}

// --- Explorer view types ---

export interface DocumentResult {
  aktenzeichen: string;
  title: string;
  fachbereich: string;
  document_type: string;
  completion_date: string;
  relevance_score: number;
  source_file?: string;
}

/** A document a generated answer cited. Named rather than inline because the
 *  review screen renders the same cards from a different response shape. */
export interface SourceRef {
  aktenzeichen: string;
  title: string;
  fachbereich?: string;
  completion_date?: string;
  source_file?: string;
}

export interface GeneratedAnswerResult {
  text: string;
  sources: SourceRef[];
  system_prompt?: string | null;
}

export interface ExternalSourceResult {
  url: string;
  label: string;
  context: string;
  cited_in: {
    aktenzeichen: string;
    title: string;
  }[];
}

// --- Ingestion types ---

export interface IngestionStatus {
  status: "idle" | "running" | "completed" | "failed";
  total_files: number;
  processed: number;
  skipped: number;
  chunks_created: number;
  errors: string[];
  current_file: string;
  started_at: string | null;
  completed_at: string | null;
  /** Indexed documents with no matching file on disk. */
  stale_documents: string[];
}

/** One Referat offered in the Fachbereich filter. */
export interface ReferatOption {
  /** The value to filter on. fachbereich_number is the indexed field. */
  number: string;
  /** Label only. Comes from the backend mapping, not from the documents,
   *  whose own Fachbereich names are inconsistent. */
  name: string;
}

/** Prompts and filter options, served by GET /api/config.
 *  Previously hardcoded in ExplorerView with a comment asking whoever edited
 *  them to keep both copies in step. */
export interface AppConfig {
  /** Keyed by question sub-mode id: fachfrage, ueberblick. */
  prompts: Record<string, string>;
  document_types: string[];
  referate: ReferatOption[];
}


// ── Evaluation harness ──────────────────────────────────────────────
//
// Served by sentra_eval, a separate process reached through the same origin:
// nginx routes /api/eval to it. Its vocabulary is the KISZ Vorlage's and stays
// German, because a Phase-4 sheet is filled in from these values.

export interface EvalRun {
  id: string;
  label: string;
  status: string;
  sentra_base_url: string;
  repeats: number;
  started_at: string;
  completed_at: string | null;
  fehler: string;
  total: number;
  done: number;
  failed: number;
  audit_ok: boolean;
}

export interface QueueCall {
  id: string;
  variant_key: string;
  repeat_index: number;
  text: string;
  sources: SourceRef[];
  http_status: number | null;
  dauer_ms: number | null;
}

export interface QueueEntry {
  test_id: string;
  kategorie: string;
  case_version_id: string;
  version: number;
  ausgangsfrage: string;
  erwartete_antwort: string;
  referenz_korrekt: string;
  referenz_falsch: string;
  grenzfall: boolean;
  gefunden_ueber: string;
  calls: QueueCall[];
  assessed: boolean;
}

export interface CheckResult {
  pruefung: string;
  ergebnis: string;
  auffaellig: boolean;
  belege: Record<string, unknown>;
}

/** Deliberately fetched only after a sheet is submitted. The queue does not
 *  carry these at all — see sentra_eval/review.py. */
export interface MachineVerdicts {
  per_call: CheckResult[];
  per_group: CheckResult[];
}

export interface VorlageOptions {
  quelle_4_3a: string[];
  quelle_4_3b: string[];
  quelle_4_3c: string[];
  reproduzierbar: string[];
  gefunden_ueber: string[];
  schweregrad: Record<string, string>;
}

export interface SubmitVerdict {
  tester: string;
  /** Keyed "<variant_key>#<repeat_index>", matching the harness. */
  kernbefunde: Record<string, string>;
  quelle_4_3a: string;
  quelle_4_3b: string;
  quelle_4_3c: string;
  schweregrad: number;
  reproduzierbar: string;
  anmerkung: string;
}

export interface Verdict extends SubmitVerdict {
  id: string;
  run_id: string;
  case_version_id: string;
  /** Derived by the harness, not submitted. */
  gefunden_ueber: string;
  kisz_meldung: boolean;
  created_at: string;
}

/** What an uploaded collection sheet did, by Test-ID.
 *
 *  Test-IDs rather than counts: "3 angelegt" leaves the author wondering which
 *  three, and the IDs are what they will look for next.
 *
 *  `freigegeben` is always empty for a sheet — an upload can only create
 *  drafts. The field exists because the same shape reports a CLI import, where
 *  approval is possible. */
export interface ImportReport {
  angelegt: string[];
  aktualisiert: string[];
  unveraendert: string[];
  freigegeben: string[];
}

/** How a round split across the three Stufen.
 *
 *  `grenzfaelle` overlaps the others rather than being a fourth bucket: a
 *  Grenzfall always reaches a human, whatever the checks said. */
export interface TriageSummary {
  gesamt: number;
  stufe_2: number;
  stufe_3: number;
  grenzfaelle: number;
  unauffaellig: number;
}

/** Stufe 1 against a human — section 6's headline measurement.
 *
 *  `abweichungsquote` is null until somebody has assessed a case, and that is
 *  not the same fact as zero. Zero means the checks and the reviewers agreed
 *  on everything; null means nobody has looked yet. Rendering one as the other
 *  would report perfect agreement from an empty round. */
export interface Agreement {
  einig: number;
  zu_streng: number;
  zu_grosszuegig: number;
  nicht_bewertet: number;
  abweichungsquote: number | null;
}

/** The Vorlage's Phase-4 documentation sheet, one per case.
 *
 *  German field names on purpose: a sheet is what gets filed, and translating
 *  the vocabulary is how the sheet and the template drift apart. */
export interface Sheet {
  test_id: string;
  datum: string;
  tester: string;
  kategorie: string;
  angewendete_techniken: string[];
  urspruenglicher_prompt: string;
  geprüfte_varianten: string[];
  varianten_erstellt_durch: string;
  varianten_freigegeben_durch: string;
  automatisiert_geprueft_durch: string;
  ergebnis_automatikpruefung: string;
  gefunden_ueber: string;
  manuell_geprueft_durch: string;
  kernbefund_je_variante: Record<string, string>;
  quellenbewertung_4_3a: string;
  quellenbewertung_4_3b: string;
  quellenbewertung_4_3c: string;
  schweregrad: number | null;
  reproduzierbar: string;
  freitext_anmerkung: string;
}

/** The monthly Trendauswertung, across every round. */
export interface Trend {
  runden: number;
  faelle: number;
  nach_kategorie: Record<string, number>;
  schweregrade: Record<string, number>;
  kisz_meldungen: number;
  haeufigste_befunde: Record<string, number>;
  abweichung: Agreement;
}
