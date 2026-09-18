import type { SentraUser } from "@/types";
import { request } from "@/lib/api";

/** Administering who can sign in.
 *
 *  Admin only, and the backend enforces that — these calls answering 403 is
 *  the expected outcome for anybody else, not an error to design around.
 *
 *  No endpoint here returns a password or a hash, and none should ever be
 *  asked to. */
export function fetchUsers(): Promise<SentraUser[]> {
  return request("/users", { label: "Benutzer konnten nicht geladen werden" });
}

export function createUser(
  benutzername: string,
  rolle: string,
  passwort: string,
): Promise<SentraUser> {
  return request("/users", {
    method: "POST",
    body: { benutzername, rolle, passwort },
    label: "Der Benutzer konnte nicht angelegt werden",
    statusMessages: { 409: "Dieser Benutzername ist bereits vergeben." },
  });
}

/** Change a role, a password, or both. Omitted fields are left alone, so a
 *  role change need not resend a password. */
export function updateUser(
  benutzername: string,
  changes: { rolle?: string; passwort?: string },
): Promise<SentraUser> {
  return request(`/users/${encodeURIComponent(benutzername)}`, {
    method: "PATCH",
    body: changes,
    label: "Der Benutzer konnte nicht geändert werden",
  });
}

export async function deleteUser(benutzername: string): Promise<void> {
  await request(`/users/${encodeURIComponent(benutzername)}`, {
    method: "DELETE",
    label: "Der Benutzer konnte nicht gelöscht werden",
  });
}
