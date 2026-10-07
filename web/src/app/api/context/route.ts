import { proxyJson } from "@/lib/ai-service/proxy";

export const GET = (request: Request) => proxyJson(request, "/api/v1/context");
