import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { AppConfig, Session } from "@/types";

/** Who is offered the prompt editor.
 *
 *  Replacing the system prompt is an experiment rather than a question, so it
 *  belongs to the reviewer — #191, item 0b of the security notes. An answer
 *  produced under a caller's own prompt is not SENTRA's answer, and a round
 *  that measured those would be measuring something else.
 *
 *  **This is not the access control and nothing here should be read as it.**
 *  `api/auth.py::PromptRights` refuses the field, and the field is reachable
 *  with curl whatever this file does. Hiding the button spares a reader a
 *  control that would answer 403, which is the same trade `views.ts` makes for
 *  the tabs.
 */

const CONFIG: AppConfig = {
  prompts: {
    fachfrage: "Du bist ein Assistent der Wissenschaftlichen Dienste.",
    ueberblick: "Erstelle einen strukturierten Überblick.",
  },
  document_types: [],
  referate: [],
};

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchConfig: () => Promise.resolve(CONFIG) };
});

const { ExplorerView } = await import("./ExplorerView");

const BUTTON = /KI-Anweisungen/;

function signedInAs(rolle: string): Session {
  return { benutzername: "jemand", rolle };
}

/** The button only exists in the Fragen tab, which is not the one the screen
 *  opens on. Every case here has to switch first, so a test that forgot would
 *  otherwise pass by finding nothing. */
async function openFragen() {
  const { default: userEvent } = await import("@testing-library/user-event");
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /Fragen/ }));
}

describe("the prompt editor", () => {
  it("is offered to a reviewer", async () => {
    render(<ExplorerView session={signedInAs("pruefer")} />);
    await openFragen();

    await waitFor(() => expect(screen.getByTitle(BUTTON)).toBeInTheDocument());
  });

  it("is offered to an admin", async () => {
    render(<ExplorerView session={signedInAs("admin")} />);
    await openFragen();

    await waitFor(() => expect(screen.getByTitle(BUTTON)).toBeInTheDocument());
  });

  it("is not offered to a reader", async () => {
    render(<ExplorerView session={signedInAs("leser")} />);
    await openFragen();

    // Waited for rather than asserted immediately: the button is gated on the
    // config arriving as well, so an assertion that ran before the fetch
    // resolved would pass for the wrong reason.
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toBeInTheDocument(),
    );
    expect(screen.queryByTitle(BUTTON)).not.toBeInTheDocument();
  });

  it("is offered when no login is configured", async () => {
    // Null is what App passes when nobody can sign in, and then everything is
    // on offer — which is what the backend does in that case too.
    render(<ExplorerView session={null} />);
    await openFragen();

    await waitFor(() => expect(screen.getByTitle(BUTTON)).toBeInTheDocument());
  });

  it("is offered when the session is not passed at all", async () => {
    // The prop is optional, so a caller that has not been updated must not
    // silently lose the control. Failing open is right here and only here: the
    // backend is what refuses, and a UI that hid a control because a prop was
    // missing would look like a permissions bug.
    render(<ExplorerView />);
    await openFragen();

    await waitFor(() => expect(screen.getByTitle(BUTTON)).toBeInTheDocument());
  });

  it("does not hide the search itself from a reader", async () => {
    render(<ExplorerView session={signedInAs("leser")} />);
    await openFragen();

    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });
});
