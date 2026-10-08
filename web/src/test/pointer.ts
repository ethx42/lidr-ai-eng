import { vi } from "vitest";

// jsdom has no matchMedia: answers the pointer media query as a mouse ("fine") or a touch screen ("coarse") would.
export const stubPointer = (pointer: "fine" | "coarse") =>
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query === `(pointer: ${pointer})`,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
