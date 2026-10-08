import { proxyPost } from "@/lib/ai-service/proxy";

// Starts a conversation: the AI service issues the id; nothing from the client is forwarded.
export const POST = (request: Request) => proxyPost(request, "/sessions");
