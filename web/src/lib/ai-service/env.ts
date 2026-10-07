import "server-only";
import * as z from "zod";

// not z.httpUrl(): it demands a dotted hostname, which rejects Compose service names and localhost
const schema = z.object({
  AI_SERVICE_URL: z.url({ protocol: /^https?$/, error: "AI_SERVICE_URL must be an absolute http(s) URL, e.g. http://ai-service:8000" }).transform((url) => url.replace(/\/+$/, "")),
});

export const serverEnv = () => schema.parse({ AI_SERVICE_URL: process.env.AI_SERVICE_URL });
