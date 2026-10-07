import { useCallback, useEffect, useMemo, useState } from "react";
import type { StreamState } from "@/lib/estimate/types";
import { useEstimateStream } from "./use-estimate-stream";

type Done = Extract<StreamState, { status: "done" }>;
// `kept`: the completed estimate a regenerate that was stopped or failed falls back to (stop never costs finished work).
export type Turn = { id: string; transcription: string; state: StreamState; kept?: Done };
type StoredTurn = { id: string; transcription: string; state: Done };

const STORAGE_KEY = "estimator.thread.v1";
const MAX_STORED = 20;

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
// Only completed turns are stored; the result itself stays unchecked wire data, read through guards by the view.
const isStoredTurn = (value: unknown): value is StoredTurn =>
  isObject(value) &&
  typeof value.id === "string" &&
  typeof value.transcription === "string" &&
  isObject(value.state) &&
  value.state.status === "done" &&
  isObject(value.state.result);

const load = (): Turn[] => {
  if (typeof window === "undefined") return []; // server render: the client reads storage when it hydrates
  try {
    const stored: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(stored) ? stored.filter(isStoredTurn).slice(-MAX_STORED) : [];
  } catch {
    return []; // corrupted JSON or storage disabled
  }
};

const lastDone = (turn: Turn) => (turn.state.status === "done" ? turn.state : turn.kept);

// Over quota, the oldest turns go first; when not even one fits, the key is removed rather than left stale.
const write = (turns: StoredTurn[]): void => {
  if (turns.length === 0) return sessionStorage.removeItem(STORAGE_KEY);
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(turns));
  } catch {
    write(turns.slice(1));
  }
};

const save = (turns: Turn[]) => {
  const stored = turns.flatMap((turn) => {
    const done = lastDone(turn);
    return done ? [{ id: turn.id, transcription: turn.transcription, state: done }] : [];
  });
  try {
    write(stored.slice(-MAX_STORED));
  } catch {
    // storage disabled: the thread still works for this page view
  }
};

let sequence = 0;
const newId = () => `${Date.now().toString(36)}-${(sequence++).toString(36)}`;

// The turn as it shows `state`: a stopped or failed attempt keeps the last completed estimate.
const withState = (turn: Turn, state: StreamState): Turn => {
  const done = lastDone(turn);
  const unfinished = state.status === "cancelled" || state.status === "error";
  return { id: turn.id, transcription: turn.transcription, state, ...(unfinished && done && { kept: done }) };
};

// A turn that stops being the active one keeps its last state; a stream it leaves running counts as stopped.
const settle = (turns: Turn[], activeId: string | null, state: StreamState) =>
  turns.map((turn) => (turn.id === activeId ? withState(turn, state.status === "streaming" ? { status: "cancelled", partial: state.partial } : state) : turn));

// Each turn is estimated on its own (no conversation memory): one stream at a time, owned by the active turn.
// `settled` holds every turn as it was before the active stream started; the live state is laid over the active one.
export const useThread = () => {
  const { state, start, stop, current } = useEstimateStream();
  const [settled, setSettled] = useState<Turn[]>(load);
  const [activeId, setActiveId] = useState<string | null>(null);

  const turns = useMemo(() => settled.map((turn) => (turn.id === activeId ? withState(turn, state) : turn)), [settled, activeId, state]);
  const streaming = state.status === "streaming";

  useEffect(() => {
    if (!streaming) save(turns);
  }, [turns, streaming]);

  // `current()` rather than the rendered state: a result that arrived but is not rendered yet must not count as stopped.
  const send = useCallback(
    (transcription: string) => {
      if (!transcription.trim()) return;
      const id = newId();
      const latest = current();
      setSettled((turns) => [...settle(turns, activeId, latest), { id, transcription, state: { status: "idle" } }]);
      setActiveId(id);
      start({ transcription });
    },
    [activeId, current, start],
  );

  // Regenerate skips the exact-match cache so it really produces a new answer.
  const regenerate = useCallback(
    (turnId: string) => {
      const turn = settled.find(({ id }) => id === turnId);
      if (!turn) return;
      const latest = current();
      setSettled((turns) => settle(turns, activeId, latest));
      setActiveId(turnId);
      start({ transcription: turn.transcription }, { refresh: true });
    },
    [settled, activeId, current, start],
  );

  return { turns, send, stop, regenerate };
};
