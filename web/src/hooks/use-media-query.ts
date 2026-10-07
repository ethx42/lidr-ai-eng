import { useCallback, useSyncExternalStore } from "react";

// Whether a media query matches, kept in sync; `serverValue` stands in where there is no window.
export const useMediaQuery = (query: string, serverValue = false) => {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => serverValue);
};
