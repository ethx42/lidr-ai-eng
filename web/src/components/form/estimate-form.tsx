"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ChevronRight, Upload } from "lucide-react";
import { type ChangeEvent, type FormEvent, type ReactNode, type Ref, useEffect, useId, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { SampleMenu, sampleDraft } from "@/components/chat/sample-picker";
import { DEFAULT_MAX_CHARS } from "@/components/service-context";
import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { useDraft } from "@/hooks/use-draft";
import { useHydrated } from "@/hooks/use-hydrated";
import type { components } from "@/lib/ai-service/schema";
import { focusForTyping } from "@/lib/focus";
import type { Sample } from "@/lib/samples";
import { countChars, formatChars, formatCount } from "@/lib/transcript";
import { cn } from "@/lib/utils";
import { DETAIL_LEVELS, OUTPUT_FORMATS, PROJECT_TYPES } from "@/lib/estimate/choices";
import { DEFAULT_VALUES, DETAIL_LEVEL_LABELS, type EstimateParams, estimateFormSchema, OUTPUT_FORMAT_LABELS, PROJECT_TYPE_LABELS, toRequest } from "./estimate-form-schema";
import { Segmented } from "./segmented";

// `edit` puts text back for editing, asking first when it would replace a different draft (false then), and focuses the
// transcript unless `focus` is false; `what` completes "Replace your draft with …?". `clear` empties the transcript once
// it has been sent, keeping the choices. `focus` moves focus to the transcript where typing is the next step without
// covering the page (a fine pointer); false on a touch screen.
export type EstimateFormHandle = { edit: (text: string, what?: string, opts?: { focus?: boolean }) => boolean; clear: () => void; focus: () => boolean };
type Props = {
  onSubmit: (body: components["schemas"]["EstimateRequest"], opts: { promptVersion: string }) => void;
  versions?: string[]; // absent: no prompt-version choice (a conversation's endpoints take none)
  defaultVersion?: string; // "" while unknown: the AI service applies its own
  maxChars?: number;
  transcriptLabel?: string;
  attachments?: ReactNode; // shown under the transcript (the conversation's dropzone)
  samples?: Sample[];
  compact?: boolean; // turns sit above the composer, so the empty transcript box starts short
  onParamsChange?: (params: EstimateParams) => void;
  handle?: Ref<EstimateFormHandle>;
};

// UTF-8 needs at most 4 bytes per character: a larger file cannot fit the limit, so it is refused before it is read.
const BYTES_PER_CHAR = 4;

const isApple = () => /Mac|iPhone|iPad/.test(navigator.userAgent);
const isText = (file: File) => file.type === "text/plain" || /\.txt$/i.test(file.name);

// The typed request (spec §6.5): transcript, the three choices, the prompt version behind Advanced, one Estimate.
// The form keeps its values after a run, so the next estimate starts from the last one.
export const EstimateForm = ({
  onSubmit,
  versions,
  defaultVersion = "",
  maxChars = DEFAULT_MAX_CHARS,
  transcriptLabel = "Transcript",
  attachments,
  samples = [],
  compact = false,
  onParamsChange,
  handle,
}: Props) => {
  const id = useId();
  const { control, getValues, setValue, setError, clearErrors, handleSubmit, resetField } = useForm({ resolver: zodResolver(estimateFormSchema), defaultValues: DEFAULT_VALUES });
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const samplesRef = useRef<HTMLButtonElement>(null);
  const uploadRef = useRef<HTMLButtonElement>(null);
  const askedFrom = useRef<HTMLElement | null>(null); // the control that raised the replace question
  const [advanced, setAdvanced] = useState(false);
  const transcript = useWatch({ control, name: "transcription" });
  const length = useMemo(() => countChars(transcript), [transcript]);
  const over = length > maxChars;
  const apple = useHydrated() && isApple(); // the server cannot know the platform
  const [counterId, overId, overById, errorId, confirmId, advancedId, versionId] = ["counter", "over", "over-by", "error", "confirm", "advanced", "version"].map(
    (part) => `${id}-${part}`,
  );

  const write = (text: string) => setValue("transcription", text, { shouldDirty: true, shouldValidate: true });
  const draft = useDraft(() => getValues("transcription"), write);
  const { pending } = draft;

  // A pending replacement takes focus on its safe choice. Either answer removes the question, so focus returns to the
  // transcript, or on a touch screen (where that would open the keyboard) to the control that asked, never to the page.
  useEffect(() => {
    if (pending) keepRef.current?.focus();
  }, [pending]);
  const answer = (replace: boolean) => {
    if (replace) draft.confirm();
    else draft.cancel();
    if (!focusForTyping(inputRef.current)) (askedFrom.current ?? samplesRef.current)?.focus();
  };
  const focusAfterPick = () => {
    if (!pending) return focusForTyping(inputRef.current);
    keepRef.current?.focus();
    return true;
  };

  // The rejected transcript goes back for editing; the user asked to edit, so it takes focus on any pointer.
  useImperativeHandle(handle, () => ({
    edit: (text, what = "the transcript to shorten", { focus = true } = {}) => {
      askedFrom.current = null;
      const replaced = draft.replace({ text, what });
      if (replaced && focus) inputRef.current?.focus();
      return replaced;
    },
    clear: () => resetField("transcription"), // also clears its error and dirty state, so no "empty" message shows
    focus: () => focusForTyping(inputRef.current),
  }));

  const paramsChanged = () => {
    const { project_type, detail_level, output_format, prompt_version } = getValues();
    onParamsChange?.({ project_type, detail_level, output_format, prompt_version });
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = ""; // the same file can be chosen again
    if (!file) return;
    const refuse = (message: string) => setError("transcription", { type: "file", message }, { shouldFocus: false });
    if (!isText(file)) return refuse(`“${file.name}” is not a .txt file. Choose a plain text file.`);
    if (file.size > maxChars * BYTES_PER_CHAR) return refuse(`“${file.name}” is too large: a transcript holds at most ${formatCount(maxChars)} characters.`);
    const text = await file.text();
    if (!text.trim()) return refuse(`“${file.name}” is empty.`);
    askedFrom.current = uploadRef.current;
    if (draft.replace({ text, what: `the file “${file.name}”` })) focusForTyping(inputRef.current);
  };

  // Over the limit the attempt lands on the transcript, whose live message already says what to do.
  const submit = (event?: FormEvent) => {
    if (over) {
      event?.preventDefault();
      inputRef.current?.focus();
      return;
    }
    void handleSubmit((values) => onSubmit(toRequest(values), { promptVersion: values.prompt_version || defaultVersion }))(event);
  };

  return (
    <form aria-label="Estimate request" noValidate onSubmit={submit} className="flex shrink-0 flex-col gap-4 border-b px-4 py-4 sm:px-6">
      {pending && (
        <div
          role="group"
          aria-labelledby={confirmId}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.preventDefault(); // handled here: the stream's Esc-to-stop listener skips it
            answer(false);
          }}
          className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border bg-surface px-3 py-2"
        >
          <p id={confirmId} className="text-sm">{`Replace your draft with ${pending.what}?`}</p>
          <div className="ml-auto flex gap-2">
            <Button type="button" variant="secondary" size="sm" onClick={() => answer(true)}>
              Replace draft
            </Button>
            <Button ref={keepRef} type="button" variant="ghost" size="sm" onClick={() => answer(false)}>
              Keep my draft
            </Button>
          </div>
        </div>
      )}
      <Controller
        name="transcription"
        control={control}
        render={({ field, fieldState }) => (
          <Field data-invalid={fieldState.invalid || over} className="gap-1.5">
            <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
              <FieldLabel htmlFor={field.name} className="mr-auto">
                {transcriptLabel}
              </FieldLabel>
              {samples.length > 0 && (
                <SampleMenu
                  triggerRef={samplesRef}
                  samples={samples}
                  onPick={(sample) => {
                    askedFrom.current = samplesRef.current;
                    draft.replace(sampleDraft(sample));
                  }}
                  onPicked={focusAfterPick}
                />
              )}
              <Button ref={uploadRef} type="button" variant="ghost" size="sm" onClick={() => fileRef.current?.click()}>
                <Upload />
                Upload .txt
              </Button>
              <input ref={fileRef} type="file" accept=".txt,text/plain" hidden onChange={(event) => void upload(event)} />
            </div>
            <Textarea
              {...field}
              id={field.name}
              ref={(element) => {
                field.ref(element);
                inputRef.current = element;
              }}
              onChange={(event) => {
                if (fieldState.error?.type === "file") clearErrors("transcription");
                field.onChange(event);
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey)) return;
                if (event.nativeEvent.isComposing || event.keyCode === 229) return; // IME composition (Safari reports it only via 229)
                event.preventDefault(); // Cmd/Ctrl+Enter estimates; a plain Enter keeps inserting a newline
                submit();
              }}
              placeholder="Paste the meeting transcript, load a sample or upload a .txt file"
              aria-invalid={fieldState.invalid || over || undefined}
              aria-describedby={[counterId, over && overId, over && overById, fieldState.invalid && errorId].filter(Boolean).join(" ")}
              // Grows with the text up to the window less the header and the composer's other rows (45% of a short window at
              // least), so a transcript that fits the window shows in full instead of scrolling in a fixed box (svh: steady
              // while a mobile URL bar shows or hides).
              className={cn("max-h-[max(45svh,calc(100svh-24rem))] bg-card", compact ? "min-h-12" : "min-h-28")}
            />
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <FieldError id={errorId} errors={[fieldState.error]} className="text-xs" />
                {/* Always mounted, and its text only changes when the limit is crossed, so it is announced once; the
                    running count sits outside it. */}
                <p className={cn("text-xs text-destructive", !over && "sr-only")}>
                  <span id={overId} role="status">
                    {over ? "Shorten the transcript to estimate it." : ""}
                  </span>{" "}
                  {over && <span id={overById}>{`It is ${formatChars(length - maxChars)} over the limit.`}</span>}
                </p>
              </div>
              <span id={counterId} className={cn("num shrink-0 text-xs", over ? "text-destructive" : length > maxChars * 0.9 ? "text-warning" : "text-muted-foreground")}>
                {`${formatCount(length)} / ${formatCount(maxChars)} `}
                <span className="sr-only">characters</span>
              </span>
            </div>
          </Field>
        )}
      />
      {attachments}
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <Controller
          name="project_type"
          control={control}
          render={({ field }) => (
            <Segmented
              label="Project type"
              options={PROJECT_TYPES}
              labels={PROJECT_TYPE_LABELS}
              value={field.value}
              onChange={(value) => {
                field.onChange(value);
                paramsChanged();
              }}
            />
          )}
        />
        <Controller
          name="detail_level"
          control={control}
          render={({ field }) => (
            <Segmented
              label="Detail level"
              options={DETAIL_LEVELS}
              labels={DETAIL_LEVEL_LABELS}
              value={field.value}
              onChange={(value) => {
                field.onChange(value);
                paramsChanged();
              }}
            />
          )}
        />
        <Controller
          name="output_format"
          control={control}
          render={({ field }) => (
            <Segmented
              label="Output format"
              options={OUTPUT_FORMATS}
              labels={OUTPUT_FORMAT_LABELS}
              value={field.value}
              onChange={(value) => {
                field.onChange(value);
                paramsChanged();
              }}
            />
          )}
        />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {versions && (
          <>
            <Button type="button" variant="ghost" size="sm" aria-expanded={advanced} aria-controls={advancedId} onClick={() => setAdvanced(!advanced)}>
              <ChevronRight className={cn("transition-transform", advanced && "rotate-90")} />
              Advanced
            </Button>
            <div id={advancedId} hidden={!advanced} className="flex items-center gap-2">
              <label htmlFor={versionId} className="text-sm">
                Prompt version
              </label>
              <Controller
                name="prompt_version"
                control={control}
                render={({ field }) => (
                  <select
                    id={versionId}
                    ref={field.ref}
                    name={field.name}
                    value={field.value || defaultVersion}
                    onBlur={field.onBlur}
                    onChange={(event) => {
                      field.onChange(event.target.value);
                      paramsChanged();
                    }}
                    className="h-7 rounded-md border border-input bg-background px-2 font-mono text-xs"
                  >
                    {versions.length === 0 ? (
                      <option value="">Service default</option>
                    ) : (
                      versions.map((version) => (
                        <option key={version} value={version}>
                          {version}
                        </option>
                      ))
                    )}
                  </select>
                )}
              />
            </div>
          </>
        )}
        <Button type="submit" aria-describedby={over ? `${overId} ${overById}` : undefined} aria-keyshortcuts={apple ? "Meta+Enter" : "Control+Enter"} className="ml-auto min-w-28">
          Estimate
          {/* opacity-80 keeps 4.5:1 on the light primary, at rest and hovered (70 gave 4.1:1, flagged by axe in the e2e run) */}
          <kbd aria-hidden className="hidden font-sans text-xs opacity-80 sm:inline">
            {apple ? "⌘↵" : "Ctrl ↵"}
          </kbd>
        </Button>
      </div>
    </form>
  );
};
