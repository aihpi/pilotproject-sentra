import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Session } from "@/types";

/** Signing in, and what each role is offered.
 *
 *  Three properties are worth more than the tab lists.
 *
 *  **An anonymous visitor is a reader.** Not an admin, which is what "no
 *  session means everything is allowed" amounted to before #209, and which on
 *  the deployed instance offered Administration — the screen that creates
 *  users — to anybody who knew the site password.
 *
 *  **A deployment that cannot authenticate anybody must not offer a login.**
 *  There would be nothing to sign in as, and a sign-in box in front of an open
 *  installation is a lie about what it is.
 *
 *  **Hiding a tab is not access control**, and these tests should not be read
 *  as testing it. The backend refuses; this decides what is worth offering,
 *  because a button that answers 403 is worse than a button that is not there.
 */

const fetchSession = vi.fn();
const loginConfigured = vi.fn();
const logout = vi.fn();

vi.mock("@/lib/session", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/session")>("@/lib/session");
  return {
    ...actual,
    fetchSession: () => fetchSession(),
    loginConfigured: () => loginConfigured(),
    logout: () => logout(),
    login: vi.fn(),
  };
});

// The views themselves reach for the API on mount; none of that is under test.
vi.mock("@/components/explorer/ExplorerView", () => ({
  ExplorerView: () => <div>Explorer-Inhalt</div>,
}));
vi.mock("@/components/DocumentsView", () => ({
  DocumentsView: ({ canIngest }: { canIngest: boolean }) => (
    <div>Dokumente-Inhalt{canIngest ? " mit Einlesen" : ""}</div>
  ),
}));
vi.mock("@/components/evaluation/EvaluationView", () => ({
  EvaluationView: () => <div>Auswertung-Inhalt</div>,
}));
vi.mock("@/components/administration/AdministrationView", () => ({
  AdministrationView: () => <div>Administration-Inhalt</div>,
}));

const { default: App } = await import("@/App");

const LESER: Session = { benutzername: "gast", rolle: "leser" };
const PRUEFER: Session = { benutzername: "wd", rolle: "pruefer" };
const ADMIN: Session = { benutzername: "chef", rolle: "admin" };

function given({ configured = true, session = null as Session | null } = {}) {
  loginConfigured.mockResolvedValue(configured);
  fetchSession.mockResolvedValue(session);
  render(<App />);
}

const TABS = ["Suche", "Dokumente", "Auswertung", "Administration"];

async function visibleTabs(): Promise<string[]> {
  await screen.findByRole("button", { name: "Suche" });
  return TABS.filter(
    (tab) => screen.queryByRole("button", { name: tab }) !== null,
  );
}

beforeEach(() => {
  [fetchSession, loginConfigured, logout].forEach((m) => m.mockReset());
  logout.mockResolvedValue(undefined);
});

describe("when no login is configured", () => {
  it("offers no way to sign in, because there would be nothing to sign in as", async () => {
    given({ configured: false, session: null });

    expect(
      await screen.findByRole("button", { name: "Suche" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Anmelden" }),
    ).not.toBeInTheDocument();
  });

  it("still offers only a reader's tabs", async () => {
    /** The backend is open in this case and the UI is not, deliberately. The
     *  divergence is the point of #209: Administration creates users, and an
     *  installation that cannot say who anybody is should not put that in
     *  front of them. */
    given({ configured: false, session: null });

    expect(await visibleTabs()).toEqual(["Suche", "Dokumente"]);
  });

  it("keeps the ingest button, because the backend would allow it", async () => {
    given({ configured: false, session: null });

    await userEvent.click(await screen.findByRole("button", { name: "Dokumente" }));
    expect(screen.getByText("Dokumente-Inhalt mit Einlesen")).toBeInTheDocument();
  });

  it("offers no way to sign out of a session that does not exist", async () => {
    given({ configured: false, session: null });

    await screen.findByRole("button", { name: "Suche" });
    expect(
      screen.queryByRole("button", { name: "Abmelden" }),
    ).not.toBeInTheDocument();
  });
});

describe("when a login is configured but nobody has used it", () => {
  it("does not demand one", async () => {
    /** The ordinary visitor is a WD staffer who only searches. Putting a
     *  password box in front of that is asking for an account nobody issued. */
    given({ configured: true, session: null });

    expect(
      await screen.findByRole("button", { name: "Suche" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Anmeldung")).not.toBeInTheDocument();
  });

  it("offers a reader's tabs and nothing more", async () => {
    given({ configured: true, session: null });

    expect(await visibleTabs()).toEqual(["Suche", "Dokumente"]);
  });

  it("withholds the ingest button, because the backend would refuse it", async () => {
    given({ configured: true, session: null });

    await userEvent.click(await screen.findByRole("button", { name: "Dokumente" }));
    expect(screen.getByText("Dokumente-Inhalt")).toBeInTheDocument();
  });

  it("offers a way in, which can be cancelled", async () => {
    given({ configured: true, session: null });

    await userEvent.click(await screen.findByRole("button", { name: "Anmelden" }));
    expect(screen.getByText("Anmeldung")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Zurück zur Suche" }),
    );
    expect(screen.queryByText("Anmeldung")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suche" })).toBeInTheDocument();
  });

  it("does not flash anything at somebody who is already signed in", async () => {
    /** Nothing renders until the first fetch lands. Showing the signed-out
     *  header and replacing it half a second later tells a signed-in person
     *  they are not. */
    given({ configured: true, session: ADMIN });

    expect(
      screen.queryByRole("button", { name: "Anmelden" }),
    ).not.toBeInTheDocument();
    await screen.findByRole("button", { name: "Suche" });
  });
});

describe("what each role is offered", () => {
  it("a reader gets search and documents", async () => {
    given({ session: LESER });

    expect(await visibleTabs()).toEqual(["Suche", "Dokumente"]);
  });

  it("a reviewer also gets Auswertung", async () => {
    given({ session: PRUEFER });

    expect(await visibleTabs()).toEqual(["Suche", "Dokumente", "Auswertung"]);
  });

  it("an admin gets everything", async () => {
    given({ session: ADMIN });

    expect(await visibleTabs()).toEqual(TABS);
  });

  it("an unknown role is offered nothing rather than everything", async () => {
    /** It means the backend has roles this build does not know about, and
     *  guessing upwards is the wrong way to be wrong. */
    given({ session: { benutzername: "neu", rolle: "irgendwas" } });

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Suche" })).toBeNull(),
    );
    expect(screen.getByText(/fehlt die nötige Rolle/)).toBeInTheDocument();
  });
});

describe("who is signed in", () => {
  it("is shown, with the role", async () => {
    given({ session: PRUEFER });

    expect(await screen.findByText("wd")).toBeInTheDocument();
    expect(screen.getByText("pruefer")).toBeInTheDocument();
  });

  it("can sign out, and lands back as a reader rather than at a login", async () => {
    given({ session: ADMIN });
    await screen.findByRole("button", { name: "Suche" });

    await userEvent.click(screen.getByRole("button", { name: "Abmelden" }));

    expect(
      await screen.findByRole("button", { name: "Anmelden" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Anmeldung")).not.toBeInTheDocument();
    expect(await visibleTabs()).toEqual(["Suche", "Dokumente"]);
    expect(logout).toHaveBeenCalled();
  });

  it("is moved off a tab that signing out took away", async () => {
    given({ session: ADMIN });
    await userEvent.click(
      await screen.findByRole("button", { name: "Administration" }),
    );
    expect(screen.getByText("Administration-Inhalt")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Abmelden" }));

    expect(await screen.findByText("Explorer-Inhalt")).toBeInTheDocument();
    expect(screen.queryByText(/fehlt die nötige Rolle/)).toBeNull();
  });
});

describe("the role ordering matches the backend", () => {
  it("is least to most", async () => {
    const { ROLES } = await import("@/lib/session");

    // sentra.api.identity.ROLES. Nothing can enforce this across two
    // languages, so it is written down in both and asserted here.
    expect(ROLES).toEqual(["leser", "pruefer", "admin"]);
  });
});
