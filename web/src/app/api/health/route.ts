// Container healthcheck: the web server is up; deliberately does not call the AI service.
export const GET = () => Response.json({ status: "ok" });
