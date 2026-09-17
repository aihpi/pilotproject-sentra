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
