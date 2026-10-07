import "server-only";
import * as z from "zod";

const DEFAULT_ALLOWED_HOSTS = "localhost:3000,127.0.0.1:3000";

// not z.httpUrl(): it demands a dotted hostname, which rejects Compose service names and localhost
const schema = z.object({
  AI_SERVICE_URL: z.url({ protocol: /^https?$/, error: "AI_SERVICE_URL must be an absolute http(s) URL, e.g. http://ai-service:8000" }).transform((url) => url.replace(/\/+$/, "")),
  // Host header values (host:port) the BFF answers; see the guard in proxy.ts
  ALLOWED_HOSTS: z
    .string()
    .default(DEFAULT_ALLOWED_HOSTS)
    .transform((value) => value.split(",").map((host) => host.trim().toLowerCase()).filter(Boolean))
    .refine((hosts) => hosts.length > 0, { error: "ALLOWED_HOSTS must list at least one host:port, e.g. localhost:3000" }),
});

// An empty variable counts as unset, as in the AI service's settings.
export const serverEnv = () => schema.parse({ AI_SERVICE_URL: process.env.AI_SERVICE_URL, ALLOWED_HOSTS: process.env.ALLOWED_HOSTS || undefined });
