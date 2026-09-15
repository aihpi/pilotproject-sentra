import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Each test renders into a fresh document. Without this, a query like
// getByText would find the previous test's markup and pass for the wrong
// reason, which is worse than failing.
afterEach(cleanup);

// jsdom implements no layout and no pointer capture, and Radix's Select uses
// both: opening it calls hasPointerCapture on the trigger and scrollIntoView
// on the highlighted item, and it observes the content box for resizes.
// Without these the dropdown never opens and the options are simply absent,
// which reads as "the component does not render its options" rather than as a
// missing browser API.
//
// These stand in for behaviour the tests do not assert on. Anything that
// depends on real geometry cannot be tested here and belongs in a browser.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
