import { proxyJson, sessionNotFound, sessionPath } from "@/lib/ai-service/proxy";

// What a session knows so far (the memory panel and the history meter).
export const GET = async (request: Request, { params }: RouteContext<"/api/sessions/[id]">) => {
  const path = sessionPath((await params).id);
  return path ? proxyJson(request, path) : sessionNotFound(request, "GET");
};
