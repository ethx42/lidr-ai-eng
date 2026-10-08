// A turn's attachments, checked in the browser and again in the BFF before the upload goes on. The limits mirror the AI
// service's defaults (`ATTACHMENT_MAX_FILES`, `ATTACHMENT_MAX_BYTES` in app/config.py), which no endpoint reports; the
// service still detects each file's type by its content and enforces its own settings.
export const MAX_ATTACHMENTS = 5;
export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
// The service's body cap: every attachment at its limit plus 1 MiB for the form fields.
export const MAX_TURN_BYTES = MAX_ATTACHMENTS * MAX_ATTACHMENT_BYTES + 1024 * 1024;
export const ATTACHMENT_EXTENSIONS = [".pdf", ".docx", ".txt"] as const;
export const ATTACHMENT_ACCEPT = ATTACHMENT_EXTENSIONS.join(",");

// Browsers report types unevenly (a .docx is often "" or application/octet-stream), so the extension decides here.
export const isSupported = (name: string) => ATTACHMENT_EXTENSIONS.some((extension) => name.toLowerCase().endsWith(extension));

const size = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

export const formatBytes = (bytes: number) =>
  bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${size.format(bytes / 1024)} KB` : `${size.format(bytes / (1024 * 1024))} MB`;
