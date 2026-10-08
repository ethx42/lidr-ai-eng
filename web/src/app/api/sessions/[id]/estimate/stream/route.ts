import { proxyMultipartSse, sessionNotFound, sessionPath } from "@/lib/ai-service/proxy";
import { MAX_TURN_BYTES, MAX_TURN_PARTS } from "@/lib/session/attachments";
import { checkTurnForm } from "@/lib/session/turn-form";

// One turn of a conversation as Server-Sent Events: the multipart form is validated and rebuilt here, then streamed.
export const POST = async (request: Request, { params }: RouteContext<"/api/sessions/[id]/estimate/stream">) => {
  const path = sessionPath((await params).id);
  return path ? proxyMultipartSse(request, `${path}/estimate/stream`, { maxBodyBytes: MAX_TURN_BYTES, maxParts: MAX_TURN_PARTS, check: checkTurnForm }) : sessionNotFound(request, "POST");
};
