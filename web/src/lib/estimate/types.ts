import type { components } from "@/lib/ai-service/schema";

type Schemas = components["schemas"];

export type DeepPartial<T> = T extends (infer U)[] ? DeepPartial<U>[] : T extends object ? { [K in keyof T]?: DeepPartial<T[K]> } : T;
export type PartialBreakdown = DeepPartial<Schemas["EstimationBreakdown"]>;
export type Phase = Schemas["StatusEvent"]["phase"];
export type StreamError = { code: string; message: string; retryable: boolean; requestId?: string; details?: { type: string; msg?: string }[] };
export type StreamState =
  | { status: "idle" }
  | { status: "streaming"; phase: Phase; switchedTo?: string; partial: PartialBreakdown | null; startedAt: number }
  | { status: "done"; result: Schemas["EstimateResponse"]; requestId?: string }
  | { status: "error"; error: StreamError; partial: PartialBreakdown | null }
  | { status: "cancelled"; partial: PartialBreakdown | null };
