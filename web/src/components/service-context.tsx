"use client";

import { createContext, type ReactNode, use, useEffect, useState } from "react";
import type { components } from "@/lib/ai-service/schema";

type ServiceContext = components["schemas"]["ContextResponse"];

export const DEFAULT_MAX_CHARS = 50_000;

// undefined while loading, null when the AI service cannot provide it (or outside a provider).
const Context = createContext<ServiceContext | null | undefined>(null);

const isStrings = (value: unknown): value is string[] => Array.isArray(value) && value.every((entry) => typeof entry === "string");

// Checks the fields the shell relies on (the header chain, the form's limit and prompt versions); anything else in the
// response stays unchecked wire data.
const isServiceContext = (value: unknown): value is ServiceContext =>
  typeof value === "object" &&
  value !== null &&
  "chain" in value &&
  isStrings(value.chain) &&
  "max_transcription_chars" in value &&
  Number.isInteger(value.max_transcription_chars) &&
  Number(value.max_transcription_chars) > 0 &&
  "available_versions" in value &&
  isStrings(value.available_versions) &&
  "prompt_version" in value &&
  typeof value.prompt_version === "string";

// One browser read of GET /api/context per page load (never from a Server Component), shared by the shell: the header's
// model chain, the form's character limit, its prompt versions and the default one, and the dropzone's attachment
// limits. The inspector's Context tab reads the prompt for the form's current choices on its own (`usePromptContext`).
export const ServiceContextProvider = ({ children }: { children: ReactNode }) => {
  const [value, setValue] = useState<ServiceContext | null | undefined>(undefined);
  useEffect(() => {
    const controller = new AbortController();
    // An aborted request (unmount, StrictMode's first mount) never writes over the one that replaced it.
    const settle = (context: ServiceContext | null) => {
      if (!controller.signal.aborted) setValue(context);
    };
    fetch("/api/context", { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then((body: unknown) => settle(isServiceContext(body) ? body : null))
      .catch(() => settle(null)); // unavailable: consumers keep their defaults
    return () => controller.abort();
  }, []);
  return <Context value={value}>{children}</Context>;
};

export const useServiceContext = () => use(Context);
