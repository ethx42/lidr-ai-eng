"use client";

import { FileText, Paperclip, X } from "lucide-react";
import { type DragEvent, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ATTACHMENT_ACCEPT, formatBytes, isSupported } from "@/lib/session/attachments";
import { cn } from "@/lib/utils";

type Props = {
  maxFiles: number;
  maxBytes: number;
  files?: File[]; // the attached files, owned by the parent
  onChange: (files: File[]) => void;
};

const NO_FILES: File[] = []; // a stable default: a new [] each render would read as a new list
const sameFile = (a: File, b: File) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

// Checks a choice against what is attached and the AI service's limits; the reasons name each refused file.
const sort = (picked: File[], attached: File[], maxFiles: number, maxBytes: number) => {
  const kept = [...attached];
  const reasons: string[] = [];
  for (const file of picked) {
    if (!isSupported(file.name)) reasons.push(`${file.name} is not supported: attach PDF, DOCX or TXT files.`);
    else if (file.size === 0) reasons.push(`${file.name} is empty.`);
    else if (file.size > maxBytes) reasons.push(`${file.name} is too large: each file can be up to ${formatBytes(maxBytes)}.`);
    else if (kept.some((other) => sameFile(other, file))) reasons.push(`${file.name} is already attached.`);
    else if (kept.length >= maxFiles) reasons.push(`${file.name} was not added: up to ${maxFiles} files per message.`);
    else kept.push(file);
  }
  return { kept, reasons };
};

// Documents for this turn (spec §7.3): picked or dropped, checked here as the server would, each shown as a chip with
// its size and a remove button. Refused files are listed with the reason in a polite status region.
export const Dropzone = ({ maxFiles, maxBytes, files = NO_FILES, onChange }: Props) => {
  const [reasons, setReasons] = useState<string[]>([]);
  // The reasons are about the files they were checked against: when the parent empties the list (the turn was sent, or
  // put back without files), they go too (React's "adjusting state when a prop changes").
  const [listed, setListed] = useState(files);
  if (listed !== files) {
    setListed(files);
    if (files.length === 0) setReasons([]);
  }
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const attachRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const hintId = useId();

  const add = (picked: File[]) => {
    const { kept, reasons } = sort(picked, files, maxFiles, maxBytes);
    setReasons(reasons);
    if (kept.length !== files.length) onChange(kept);
  };

  // The removed chip's button goes away: focus moves to the next chip's, else the previous one's, else Attach.
  const remove = (index: number) => {
    const buttons = [...(listRef.current?.querySelectorAll("button") ?? [])];
    const next = buttons[index + 1] ?? buttons[index - 1] ?? attachRef.current;
    next?.focus();
    setReasons([]);
    onChange(files.filter((_, i) => i !== index));
  };

  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    add([...event.dataTransfer.files]);
  };

  return (
    <div className="flex flex-col gap-2">
      <div
        data-slot="dropzone"
        data-dragging={dragging || undefined}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragOver={(event) => {
          event.preventDefault(); // allows the drop
          setDragging(true);
        }}
        onDragLeave={(event) => {
          if (!(event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget))) setDragging(false);
        }}
        onDrop={drop}
        className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-dashed border-input px-3 py-2 transition-colors data-dragging:border-primary data-dragging:bg-accent"
      >
        <Button ref={attachRef} type="button" variant="outline" size="sm" aria-describedby={hintId} onClick={() => inputRef.current?.click()}>
          <Paperclip />
          Attach documents
        </Button>
        <span className="text-xs text-muted-foreground">or drop them here</span>
        <span id={hintId} className="text-xs text-muted-foreground sm:ml-auto">{`PDF, DOCX or TXT, up to ${maxFiles} files of ${formatBytes(maxBytes)} each`}</span>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ATTACHMENT_ACCEPT}
          aria-label="Attach documents"
          hidden
          onChange={(event) => {
            add([...(event.currentTarget.files ?? [])]);
            event.currentTarget.value = ""; // the same file can be chosen again
          }}
        />
      </div>
      {files.length > 0 && (
        <ul ref={listRef} role="list" aria-label="Attached documents" className="flex flex-wrap gap-2">
          {files.map((file, i) => (
            <li key={`${file.name}-${file.size}-${file.lastModified}`} className="flex h-7 max-w-full items-center gap-1.5 rounded-md border bg-card pr-0.5 pl-2 text-xs">
              <FileText aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
              <span title={file.name} className="min-w-0 truncate">
                {file.name}
              </span>
              <span className="num shrink-0 text-muted-foreground">{formatBytes(file.size)}</span>
              <Button type="button" variant="ghost" size="icon-xs" onClick={() => remove(i)}>
                <X />
                <span className="sr-only">{`Remove ${file.name}`}</span>
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div role="status" className={cn("flex flex-col gap-0.5 text-xs text-destructive", reasons.length === 0 && "sr-only")}>
        {reasons.map((reason, i) => (
          <p key={i}>{reason}</p>
        ))}
      </div>
    </div>
  );
};
