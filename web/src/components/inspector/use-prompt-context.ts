import { useEffect, useState } from "react";
import type { components } from "@/lib/ai-service/schema";

type Schemas = components["schemas"];

// The form's current choices; an empty prompt version means the AI service's default.
export type ContextParams = {
  project_type: Schemas["ProjectType"];
  detail_level: Schemas["DetailLevel"];
  output_format: Schemas["OutputFormat"];
  prompt_version: string;
};
// `context`: the last answer the AI service gave, unchecked wire data, undefined before the first one.
// `loading`: a request for the current choices is on its way (a retry included), so `context` may be for earlier ones.
// `failed`: the request for the current choices failed (unreachable, an error status or not JSON), so `context` is
// for earlier ones, if any; `retry` asks again for the same choices.
export type PromptContext = { context: unknown; loading: boolean; failed: boolean; retry: () => void };

const queryOf = ({ prompt_version, ...choices }: ContextParams) => {
  const query = new URLSearchParams(choices);
  if (prompt_version) query.set("prompt_version", prompt_version);
  return query.toString();
};

// GET /api/context for the given choices: the system prompt the next estimate would use. A change of choices aborts the
// request it supersedes, whose answer then never lands. A failure keeps the last answer: the page holds the run on
// screen only in memory, so it must never need a reload. `null`: the choices are not known yet (a conversation's
// prompt version comes with its session), so nothing is asked and the context stays loading.
export const usePromptContext = (params: ContextParams | null): PromptContext => {
  const query = params && queryOf(params);
  const [loaded, setLoaded] = useState<{ query: string; context: unknown } | null>(null);
  // The request for the current choices: on its way, answered, or failed. `attempt` counts retries.
  const [request, setRequest] = useState<{ query: string | null; attempt: number; status: "pending" | "answered" | "failed" }>({
    query,
    attempt: 0,
    status: "pending",
  });
  // New choices start a new request, without the last one's failure (React's "adjusting state when a prop changes").
  if (request.query !== query) setRequest({ ...request, query, status: "pending" });

  useEffect(() => {
    if (query === null) return;
    const controller = new AbortController();
    const settle = (update: () => void) => {
      if (!controller.signal.aborted) update();
    };
    fetch(`/api/context?${query}`, { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then(
        (context: unknown) =>
          settle(() => {
            setLoaded({ query, context });
            setRequest((current) => ({ ...current, status: "answered" }));
          }),
        () => settle(() => setRequest((current) => ({ ...current, status: "failed" }))),
      );
    return () => controller.abort();
  }, [query, request.attempt]);

  return {
    context: loaded?.context,
    loading: request.status === "pending",
    // A failed refetch matters only while no answer for these choices is shown.
    failed: request.status === "failed" && loaded?.query !== query,
    retry: () => setRequest((current) => ({ ...current, attempt: current.attempt + 1, status: "pending" })),
  };
};
