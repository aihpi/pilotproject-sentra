import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SentraUser, Session } from "@/types";

/** Administering who can sign in.
 *
 *  The backend enforces the two rules that matter — the last administrator and
 *  yourself — and this screen disables the controls as well. Both, deliberately:
 *  the refusal has to be real, and a button that always answers 409 is a worse
 *  way to learn a rule than a button that is visibly unavailable.
 *
 *  So these tests are about what is *offered*, not about what is permitted.
 *  Anyone reading them for the access control is in the wrong file.
 */

const fetchUsers = vi.fn();
const createUser = vi.fn();
const updateUser = vi.fn();
const deleteUser = vi.fn();

vi.mock("@/lib/users", () => ({
  fetchUsers: () => fetchUsers(),
  createUser: (...a: unknown[]) => createUser(...a),
  updateUser: (...a: unknown[]) => updateUser(...a),
  deleteUser: (...a: unknown[]) => deleteUser(...a),
}));

const { UserPane } = await import("@/components/administration/UserPane");

const CHEF: SentraUser = {
  benutzername: "chef",
  rolle: "admin",
  quelle: "Datenbank",
};
const ZWEITE: SentraUser = {
  benutzername: "zweite",
  rolle: "admin",
  quelle: "Datenbank",
};
const WD: SentraUser = {
  benutzername: "wd",
  rolle: "pruefer",
  quelle: "Datenbank",
};
const KONFIGURIERT: SentraUser = {
  benutzername: "bootstrap",
  rolle: "admin",
  quelle: "Konfiguration",
};

const SESSION: Session = { benutzername: "chef", rolle: "admin" };

async function renderWith(
  users: SentraUser[],
  session: Session | null = SESSION,
) {
  fetchUsers.mockResolvedValue(users);
  render(<UserPane session={session} />);
  await screen.findByText(users[0].benutzername);
}

beforeEach(() => {
  [fetchUsers, createUser, updateUser, deleteUser].forEach((m) =>
    m.mockReset(),
  );
  createUser.mockResolvedValue(WD);
  updateUser.mockResolvedValue(WD);
  deleteUser.mockResolvedValue(undefined);
});

describe("adding somebody", () => {
  it("sends the name, role and password", async () => {
    await renderWith([CHEF]);

    await userEvent.type(screen.getByLabelText("Benutzername"), "neu");
    await userEvent.selectOptions(screen.getByLabelText("Rolle"), "pruefer");
    await userEvent.type(screen.getByLabelText("Passwort"), "ein-passwort");
    await userEvent.click(
      screen.getByRole("button", { name: "Benutzer anlegen" }),
    );

    await waitFor(() =>
      expect(createUser).toHaveBeenCalledWith("neu", "pruefer", "ein-passwort"),
    );
  });

  it("will not submit without a password", async () => {
    await renderWith([CHEF]);

    await userEvent.type(screen.getByLabelText("Benutzername"), "neu");

    expect(
      screen.getByRole("button", { name: "Benutzer anlegen" }),
    ).toBeDisabled();
  });

  it("shows the server's reason for refusing", async () => {
    createUser.mockRejectedValue(
      new Error("Dieser Benutzername ist bereits vergeben."),
    );
    await renderWith([CHEF]);

    await userEvent.type(screen.getByLabelText("Benutzername"), "chef");
    await userEvent.type(screen.getByLabelText("Passwort"), "x");
    await userEvent.click(
      screen.getByRole("button", { name: "Benutzer anlegen" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /bereits vergeben/,
    );
  });
});

describe("what cannot be changed, and why it says so", () => {
  it("the last administrator", async () => {
    await renderWith([CHEF, WD], { benutzername: "wd", rolle: "admin" });

    expect(screen.getByText("Letzter Administrator.")).toBeInTheDocument();
  });

  it("your own account, even when another admin exists", async () => {
    /** A different mistake from the last-admin rule: this one is reached by
     *  clicking the wrong row, not by tidying up. */
    await renderWith([CHEF, ZWEITE]);

    expect(screen.getByText("Das eigene Konto.")).toBeInTheDocument();
  });

  it("a configured user, which lives in the deployment", async () => {
    await renderWith([KONFIGURIERT, WD]);

    // The row's reason, not the footnote that also mentions SENTRA_USERS.
    expect(
      screen.getByText("In SENTRA_USERS konfiguriert, hier nicht änderbar."),
    ).toBeInTheDocument();
  });

  it("but a second admin makes the first editable again", async () => {
    await renderWith([CHEF, ZWEITE, WD], {
      benutzername: "wd",
      rolle: "admin",
    });

    expect(
      screen.queryByText("Letzter Administrator."),
    ).not.toBeInTheDocument();
  });
});

describe("changing somebody", () => {
  it("a role without resending a password", async () => {
    await renderWith([CHEF, WD]);

    await userEvent.selectOptions(
      screen.getByLabelText("Rolle von wd"),
      "leser",
    );

    await waitFor(() =>
      expect(updateUser).toHaveBeenCalledWith("wd", { rolle: "leser" }),
    );
  });

  it("removing somebody", async () => {
    await renderWith([CHEF, WD]);

    await userEvent.click(
      screen.getAllByRole("button", { name: "Löschen" })[0],
    );

    await waitFor(() => expect(deleteUser).toHaveBeenCalledWith("wd"));
  });

  it("shows where each account comes from", async () => {
    await renderWith([KONFIGURIERT, WD]);

    expect(screen.getByText("Konfiguration")).toBeInTheDocument();
    expect(screen.getByText("Datenbank")).toBeInTheDocument();
  });
});
