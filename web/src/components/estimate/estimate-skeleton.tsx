import { cn } from "@/lib/utils";

// Pulses only while the enclosing estimate streams (`aria-busy`) and motion is allowed; static once the stream ends.
const PULSE = "motion-safe:group-aria-busy/estimate:animate-pulse";

// shadcn's Skeleton styling on a span, so a value placeholder is valid inside headings, spans and table cells.
export const Pending = ({ className }: { className?: string }) => (
  <span aria-hidden data-slot="skeleton" className={cn("block h-4 rounded-sm bg-muted", PULSE, className)} />
);

const rows = (count: number) => Array.from({ length: count }, (_, i) => i);

export const EstimateSkeleton = ({ shape, count = 3 }: { shape: "paragraph" | "list" | "table"; count?: number }) => (
  <div aria-hidden data-skeleton={shape} className="flex flex-col">
    {shape === "paragraph" && (
      <div className="flex flex-col gap-2 py-1">
        {["w-full", "w-11/12", "w-3/5"].slice(0, count).map((width) => (
          <Pending key={width} className={width} />
        ))}
      </div>
    )}
    {shape === "list" &&
      rows(count).map((i) => (
        <div key={i} className="flex items-center gap-3 border-b py-3">
          <Pending className="h-3 w-6" />
          <Pending className="flex-1" />
        </div>
      ))}
    {shape === "table" && (
      <>
        <div className="h-10 border-b" />
        {rows(count).map((i) => (
          <div key={i} className="grid grid-cols-[minmax(0,1fr)_7rem_4rem] items-center gap-4 border-b px-2 py-3 sm:grid-cols-[minmax(0,1fr)_11rem_5rem]">
            <Pending />
            <Pending className="h-2 rounded-full" />
            <Pending className="ml-auto w-10" />
          </div>
        ))}
      </>
    )}
  </div>
);
