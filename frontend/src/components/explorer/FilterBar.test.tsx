import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { FilterBar } from "./FilterBar";

const REFERATE = [
  { number: "WD 3", name: "Verfassung und Verwaltung" },
  { number: "EU 6", name: "Fachbereich Europa" },
];
const TYPES = ["Ausarbeitung", "Sachstand", "Sonstiges"];

function setup(props: Partial<React.ComponentProps<typeof FilterBar>> = {}) {
  const handlers = {
    onDateFromChange: vi.fn(),
    onDateToChange: vi.fn(),
    onFachbereichChange: vi.fn(),
    onDocumentTypeChange: vi.fn(),
  };
  render(
    <FilterBar
      dateFrom=""
      dateTo=""
      fachbereich={null}
      documentType={null}
      documentTypes={TYPES}
      referate={REFERATE}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("FilterBar", () => {
  it("reads as unfiltered when nothing is filtered", () => {
    setup();
    // Not the placeholders: value is `documentType || "__all__"`, so it is
    // never empty and SelectValue always shows the selected item. The
    // placeholder props on these triggers can never display.
    expect(screen.getByRole("combobox", { name: "Dokumenttyp" })).toHaveTextContent(
      "Alle Typen",
    );
    expect(screen.getByRole("combobox", { name: "Referat" })).toHaveTextContent(
      "Alle Referate",
    );
  });

  it("shows the current selection", () => {
    setup({ documentType: "Sonstiges", fachbereich: "WD 3" });
    expect(screen.getByRole("combobox", { name: "Dokumenttyp" })).toHaveTextContent(
      "Sonstiges",
    );
    expect(screen.getByRole("combobox", { name: "Referat" })).toHaveTextContent("WD 3");
  });

  it("renders while the config request is still in flight", () => {
    setup({ documentTypes: [], referate: [] });
    expect(screen.getByRole("combobox", { name: "Dokumenttyp" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Referat" })).toBeInTheDocument();
  });

  it("every filter has an accessible name", () => {
    setup();
    for (const name of ["Zeitraum von", "Zeitraum bis", "Dokumenttyp", "Referat"]) {
      expect(screen.getByRole("combobox", { name })).toBeInTheDocument();
    }
  });

  describe("the document type list", () => {
    it("offers every type it was given, including the fallback", async () => {
      setup();
      await userEvent.click(screen.getByRole("combobox", { name: "Dokumenttyp" }));

      for (const type of TYPES) {
        expect(screen.getByRole("option", { name: type })).toBeInTheDocument();
      }
      expect(screen.getByRole("option", { name: "Alle Typen" })).toBeInTheDocument();
    });

    it("reports the chosen type", async () => {
      const { onDocumentTypeChange } = setup();
      await userEvent.click(screen.getByRole("combobox", { name: "Dokumenttyp" }));
      await userEvent.click(screen.getByRole("option", { name: "Sonstiges" }));

      expect(onDocumentTypeChange).toHaveBeenCalledWith("Sonstiges");
    });

    it("reports null for the all-types entry", async () => {
      const { onDocumentTypeChange } = setup({ documentType: "Sachstand" });
      await userEvent.click(screen.getByRole("combobox", { name: "Dokumenttyp" }));
      await userEvent.click(screen.getByRole("option", { name: "Alle Typen" }));

      expect(onDocumentTypeChange).toHaveBeenCalledWith(null);
    });
  });

  describe("the Referat list", () => {
    it("offers the number as the value and carries the name as a tooltip", async () => {
      setup();
      await userEvent.click(screen.getByRole("combobox", { name: "Referat" }));

      const option = screen.getByRole("option", { name: "WD 3" });
      expect(option).toBeInTheDocument();
      // The name is a title rather than visible text: the trigger is 110px
      // wide and a full Referat name rendered into it wrecks the filter bar.
      expect(option).toHaveAttribute("title", "Verfassung und Verwaltung");
    });

    it("reports the number, which is the indexed field", async () => {
      const { onFachbereichChange } = setup();
      await userEvent.click(screen.getByRole("combobox", { name: "Referat" }));
      await userEvent.click(screen.getByRole("option", { name: "EU 6" }));

      expect(onFachbereichChange).toHaveBeenCalledWith("EU 6");
    });
  });
});
