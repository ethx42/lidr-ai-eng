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
// `context`: the latest answer, unchecked wire data (null when the AI service gave none), undefined before the first one.
// `loading`: the answer for the current choices is still on its way, so `context` may be for earlier ones.
export type PromptContext = { context: unknown; loading: boolean };

const queryOf = ({ prompt_version, ...choices }: ContextParams) => {
  const query = new URLSearchParams(choices);
  if (prompt_version) query.set("prompt_version", prompt_version);
  return query.toString();
};

// GET /api/context for the given choices: the system prompt the next estimate would use. A change of choices aborts the
// request it supersedes, whose answer then never lands.
export const usePromptContext = (params: ContextParams): PromptContext => {
  const query = queryOf(params);
  const [loaded, setLoaded] = useState<{ query: string; context: unknown } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const settle = (context: unknown) => {
      if (!controller.signal.aborted) setLoaded({ query, context });
    };
    fetch(`/api/context?${query}`, { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then(settle, () => settle(null)); // unreachable, or not JSON
    return () => controller.abort();
  }, [query]);
  return { context: loaded?.context, loading: loaded?.query !== query };
};
