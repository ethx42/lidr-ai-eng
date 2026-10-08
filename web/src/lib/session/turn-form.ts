import { DETAIL_LEVELS, OUTPUT_FORMATS, PROJECT_TYPES } from "@/lib/estimate/choices";
import { formatBytes, isSupported, MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS } from "./attachments";

type Rejection = { status: number; code: string; message: string };

const CHOICES = { project_type: PROJECT_TYPES, detail_level: DETAIL_LEVELS, output_format: OUTPUT_FORMATS } as const;
// The contract's limit for SessionEstimateForm.output_language.
const MAX_OUTPUT_LANGUAGE = 40;

const invalid = (field: string, problem: string): Rejection => ({ status: 422, code: "invalid_request", message: `${field}: ${problem}` });
// Same wording as the AI service's `invalid_attachment` messages, which name the file.
const rejected = (message: string): Rejection => ({ status: 422, code: "invalid_attachment", message });

// A turn as the session endpoint takes it: the transcript, the three choices, an optional output language and up to
// MAX_ATTACHMENTS PDF, DOCX or plain-text files. Returns a new form holding only those fields, or why it was refused.
// Empty file inputs are dropped, as the AI service does.
export const checkTurnForm = (form: FormData): FormData | Rejection => {
  const upstream = new FormData();
  const transcript = form.get("transcript");
  if (typeof transcript !== "string" || !transcript.trim()) return invalid("transcript", "required");
  upstream.set("transcript", transcript);
  for (const [field, values] of Object.entries(CHOICES)) {
    const value = form.get(field);
    if (typeof value !== "string" || !(values as readonly string[]).includes(value)) return invalid(field, `expected one of ${values.join(", ")}`);
    upstream.set(field, value);
  }
  const language = form.get("output_language");
  if (language !== null && typeof language !== "string") return invalid("output_language", "expected text");
  if (language && language.length > MAX_OUTPUT_LANGUAGE) return invalid("output_language", `at most ${MAX_OUTPUT_LANGUAGE} characters`);
  if (language) upstream.set("output_language", language);

  const entries = form.getAll("attachments");
  if (entries.some((entry) => typeof entry === "string")) return rejected("attachments must be files");
  const files = entries.filter((entry): entry is File => entry instanceof File && entry.name !== "" && entry.size > 0);
  if (files.length > MAX_ATTACHMENTS) return rejected(`too many attachments (at most ${MAX_ATTACHMENTS} per turn)`);
  for (const file of files) {
    if (!isSupported(file.name)) return rejected(`${file.name}: unsupported file type (PDF, DOCX or plain text only)`);
    if (file.size > MAX_ATTACHMENT_BYTES) return rejected(`${file.name}: larger than ${formatBytes(MAX_ATTACHMENT_BYTES)}`);
    upstream.append("attachments", file, file.name);
  }
  return upstream;
};
