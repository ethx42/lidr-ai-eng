import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

// false on the server and during hydration, true afterwards: gates UI that depends on browser-only state.
export const useHydrated = () => useSyncExternalStore(subscribe, () => true, () => false);
