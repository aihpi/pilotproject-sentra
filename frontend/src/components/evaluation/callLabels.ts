import type { QueueCall } from "@/types";

/** How an answer is labelled in the tabs and in the assessment form.
 *
 *  Its own module so both use one definition: the tab a reviewer is reading
 *  and the Kernbefund box they type into have to correspond, or the sheet
 *  records a finding against the wrong answer. */
export function labelFor(call: QueueCall): string {
  return call.variant_key === "original"
    ? `W${call.repeat_index + 1}`
    : `${call.variant_key} ${call.repeat_index + 1}`;
}

/** The key the harness stores a Kernbefund under.
 *
 *  A string contract between two codebases — see `Verdict.kernbefunde` in
 *  sentra_eval — so it is written once on this side rather than interpolated
 *  at each call site. */
export function kernbefundKey(call: QueueCall): string {
  return `${call.variant_key}#${call.repeat_index}`;
}

/** The same label, from the stored key rather than from a call.
 *
 *  A Phase-4 sheet carries `kernbefund_je_variante` keyed "<variant>#<repeat>"
 *  and has no call objects to hand — the sheet is about the round, not about
 *  what is on screen. Reading the key here rather than showing it raw keeps
 *  the sheet and the review tabs saying the same thing about the same answer,
 *  which is the whole reason `labelFor` was extracted in the first place.
 *
 *  Anything that is not in that shape is passed through. A key this does not
 *  recognise is still more useful on screen than an empty cell. */
export function labelForKey(key: string): string {
  const [variant, repeat] = key.split("#");
  if (repeat === undefined) return key;
  const index = Number(repeat);
  if (!Number.isInteger(index)) return key;
  return variant === "original" ? `W${index + 1}` : `${variant} ${index + 1}`;
}

/** A variant name on its own, as `geprüfte_varianten` lists them. */
export function labelForVariant(variant: string): string {
  return variant === "original" ? "Original" : variant;
}
