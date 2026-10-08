import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/ai-service/schema";

type SessionView = components["schemas"]["SessionView"];
// `failed`: the last load could not reach a session (the AI service is down or full, or answered something unreadable);
// `refresh()` tries again.
type State = { sessionId: string | null; view: SessionView | null; failed: boolean };

const STORAGE_KEY = "estimator.sessionId";
const INITIAL: State = { sessionId: null, view: null, failed: false };

// Storage can be unavailable (private modes, blocked site data): the session then lives for this page only.
const stored = () => {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
};
const store = (id: string) => {
  try {
    sessionStorage.setItem(STORAGE_KEY, id);
  } catch {}
};

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isCount = (value: unknown) => Number.isInteger(value) && Number(value) >= 0;
// The fields the page relies on; the metadata's own values are read through guards where they are shown.
const isView = (value: unknown): value is SessionView =>
  isObject(value) &&
  typeof value.session_id === "string" &&
  isCount(value.history_turns) &&
  isCount(value.max_turns) &&
  typeof value.prompt_version === "string" &&
  isObject(value.project_metadata);

// null for an unknown or expired session (404, also what the BFF answers for an id that is not one).
const loadView = async (id: string, signal: AbortSignal) => {
  const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { signal });
  if (res.status === 404) return null;
  const body: unknown = res.ok ? await res.json() : null;
  if (!isView(body)) throw new Error(`Unreadable session view (HTTP ${res.status})`);
  return body;
};

const createSession = async (signal: AbortSignal) => {
  const res = await fetch("/api/sessions", { method: "POST", signal });
  const body: unknown = res.ok ? await res.json() : null;
  if (!isObject(body) || typeof body.session_id !== "string") throw new Error(`No session created (HTTP ${res.status})`);
  return body.session_id;
};

// The session a load ends with, or "failed". Storing the id is the only side effect, and an aborted load skips it.
const resolveSession = async (from: string | null, signal: AbortSignal): Promise<State | "failed"> => {
  try {
    const kept = from ? await loadView(from, signal) : null;
    if (from && kept) return { sessionId: from, view: kept, failed: false };
    const id = await createSession(signal);
    if (!signal.aborted) store(id);
    const view = await loadView(id, signal);
    return view ? { sessionId: id, view, failed: false } : "failed";
  } catch {
    return "failed";
  }
};

// The conversation this tab is having: its id lives in React state and sessionStorage (a reload keeps it, a new tab
// starts its own). A stored id is checked with GET /api/sessions/{id}; when it is unknown or expired, or there is none,
// POST /api/sessions starts one, and its view is loaded. Only the latest load lands: a newer one aborts the one in flight.
export const useSession = () => {
  const [state, setState] = useState<State>(INITIAL);
  const idRef = useRef<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const load = useCallback((from: string | null) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    return resolveSession(from, controller.signal).then((next) => {
      if (controller.signal.aborted) return;
      if (next === "failed") {
        idRef.current ??= from; // a stored session that could not be checked is tried again on refresh
        setState((current) => ({ ...current, failed: true }));
        return;
      }
      idRef.current = next.sessionId;
      setState(next);
    });
  }, []);

  useEffect(() => {
    void load(stored());
    return () => controllerRef.current?.abort();
  }, [load]);

  // A new conversation: the old one is left at once, so nothing of it shows while the new one starts.
  const reset = useCallback(() => {
    idRef.current = null;
    setState(INITIAL);
    return load(null);
  }, [load]);

  // The current session's view again (or a new session, if it expired); also the retry after a failed load.
  const refresh = useCallback(() => load(idRef.current), [load]);

  return { ...state, reset, refresh };
};
