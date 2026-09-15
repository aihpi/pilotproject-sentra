import { BookOpenText, FileStack, Globe, HelpCircle, Search } from "lucide-react";

import type { SubModeConfig } from "./types";

/** What each sub-mode is called, how it is introduced, and what its input
 *  invites. Exported as data so the pills, the placeholder and the
 *  description all read the same source. */

export const DOC_SUB_MODES: SubModeConfig[] = [
  {
    id: "thema",
    label: "Nach Thema",
    icon: <Search className="h-3.5 w-3.5" />,
    placeholder: "Thema eingeben, z.B. „CO₂-Bepreisung“",
    description: "Zeigt alle vorhandenen Dokumente zu einem Thema",
  },
  {
    id: "aehnliche",
    label: "Ähnliche Dokumente",
    icon: <FileStack className="h-3.5 w-3.5" />,
    placeholder: "Aktenzeichen oder Titel eingeben…",
    description: "Findet ähnliche Dokumente zu einem bestehenden Dokument",
  },
  {
    id: "quellen",
    label: "Externe Quellen",
    icon: <Globe className="h-3.5 w-3.5" />,
    placeholder: "Thema eingeben, z.B. „CO₂-Bepreisung“",
    description: "Zeigt externe Quellen und Datenportale aus unseren Dokumenten",
  },
];

export const FRAGEN_SUB_MODES: SubModeConfig[] = [
  {
    id: "fachfrage",
    label: "Fachfrage",
    icon: <HelpCircle className="h-3.5 w-3.5" />,
    placeholder: "Frage eingeben, z.B. „Wann tritt ETS 2 in Kraft?“",
    description: "Beantwortet eine konkrete Frage mit Quellenbezug",
  },
  {
    id: "ueberblick",
    label: "Themenüberblick",
    icon: <BookOpenText className="h-3.5 w-3.5" />,
    placeholder: "Thema eingeben, z.B. „CO₂-Bepreisung“",
    description: "Erstellt eine strukturierte Übersicht zum aktuellen Wissensstand",
  },
];
