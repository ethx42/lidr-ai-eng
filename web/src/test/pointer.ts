import { vi } from "vitest";

// jsdom has no matchMedia: answers the pointer media query as a mouse ("fine") or a touch screen ("coarse") would, and
// `(min-width: 48rem)` as a viewport at least 768 px wide (`wide`, the default) or narrower. No component reads that
// query now; tests that change the viewport keep it to assert that pinning does not depend on width.
export const stubPointer = (pointer: "fine" | "coarse", { wide = true }: { wide?: boolean } = {}) =>
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query === `(pointer: ${pointer})` || (wide && query === "(min-width: 48rem)"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
