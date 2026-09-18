import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Session } from "@/types";

/** Signing in, and what each role is offered.
 *
 *  Two properties are worth more than the tab lists.
 *
 *  **A deployment that cannot authenticate anybody must not show a login.**
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
  DocumentsView: () => <div>Dokumente-Inhalt</div>,
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
  it("shows no login screen", async () => {
    given({ configured: false, session: null });

    expect(
      await screen.findByRole("button", { name: "Suche" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Anmelden" }),
    ).not.toBeInTheDocument();
  });

  it("offers every tab, matching what the backend does in that case", async () => {
    given({ configured: false, session: null });

    expect(await visibleTabs()).toEqual(TABS);
  });

  it("offers no way to sign out of a session that does not exist", async () => {
    given({ configured: false, session: null });

    await screen.findByRole("button", { name: "Suche" });
    expect(
      screen.queryByRole("button", { name: "Abmelden" }),
    ).not.toBeInTheDocument();
  });
});

describe("when a login is configured", () => {
  it("asks for one when there is no session", async () => {
    given({ configured: true, session: null });

    expect(
      await screen.findByRole("button", { name: "Anmelden" }),
    ).toBeInTheDocument();
  });

  it("does not flash the login screen at somebody who is signed in", async () => {
    /** Three states, not two: unknown while the first fetch is in flight.
     *  Rendering the login and replacing it half a second later tells a
     *  signed-in person they are not. */
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

  it("can sign out, and lands back at the login", async () => {
    given({ session: ADMIN });
    await screen.findByRole("button", { name: "Suche" });

    await userEvent.click(screen.getByRole("button", { name: "Abmelden" }));

    expect(
      await screen.findByRole("button", { name: "Anmelden" }),
    ).toBeInTheDocument();
    expect(logout).toHaveBeenCalled();
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
