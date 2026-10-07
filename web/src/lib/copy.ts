import { toast } from "sonner";

// Clipboard access needs a secure context and permission; a failure is reported, never thrown.
export const copyText = async (text: string, confirmation: string) => {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(confirmation);
  } catch {
    toast.error("Copy failed: the browser blocked clipboard access.");
  }
};
