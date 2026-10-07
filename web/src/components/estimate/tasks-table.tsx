import { TriangleAlert } from "lucide-react";
import { useId } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatHours, formatRange } from "@/lib/estimate/format";
import { type TaskPhase, type TaskView, received } from "@/lib/estimate/read";
import { EstimateSkeleton, Pending } from "./estimate-skeleton";
import { RangeBar } from "./range-bar";
import { Empty, Section } from "./section";

const PHASE_LABELS: Record<TaskPhase, string> = {
  discovery: "Discovery",
  ux_ui: "UX/UI",
  backend: "Backend",
  frontend: "Frontend",
  integrations: "Integrations",
  qa: "QA",
  devops: "DevOps",
  project_management: "Project management",
};

type Group = [phase: TaskPhase | undefined, tasks: TaskView[]];

// The final estimate groups every task under its phase, in order of first appearance.
const byPhase = (tasks: TaskView[]): Group[] => {
  const groups = new Map<TaskPhase | undefined, TaskView[]>();
  for (const task of tasks) groups.set(task.phase, [...(groups.get(task.phase) ?? []), task]);
  return [...groups];
};

// While streaming, groups are consecutive runs: a task whose phase has not arrived yet stays in the last group, and a task
// returning to an earlier phase opens a new group at the end, so rows only ever append. `byPhase` regroups once, when final.
const byRun = (tasks: TaskView[]): Group[] =>
  tasks.reduce<Group[]>((groups, task) => {
    const last = groups.at(-1);
    return last && (task.phase === undefined || task.phase === last[0])
      ? [...groups.slice(0, -1), [last[0], [...last[1], task]]]
      : [...groups, [task.phase, [task]]];
  }, []);

const sum = (values: (number | undefined)[]) => (values.every((value) => value !== undefined) ? values.reduce((a, b) => a + b, 0) : undefined);

const Basis = ({ ids, invalid }: { ids?: string[]; invalid: boolean }) => (
  <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
    {invalid && (
      <span className="inline-flex items-center gap-1 text-ungrounded">
        <TriangleAlert className="size-3.5 shrink-0" />
        No valid basis
      </span>
    )}
    {!ids ? <Pending className="h-3 w-20" /> : ids.length > 0 && <span>Based on {ids.join(", ")}</span>}
  </span>
);

const TaskRow = ({ task, max, invalidBasis }: { task: TaskView; max: number; invalidBasis: boolean }) => {
  const { name, rationale, basis, optimistic_hours: optimistic, likely_hours: likely, pessimistic_hours: pessimistic, expected_hours: expected } = task;
  const nameId = useId();
  return (
    <TableRow>
      {/* Row header named by the task name alone, so Range and Expected cells announce which task they belong to. */}
      <TableHead scope="row" aria-labelledby={name ? nameId : undefined} className="h-auto p-2 align-top font-normal wrap-anywhere whitespace-normal">
        <div className="flex flex-col gap-1">
          {name ? <span id={nameId} className="font-medium">{name}</span> : <Pending className="w-2/3" />}
          {rationale ? <span className="text-xs text-muted-foreground">{rationale}</span> : <Pending className="h-3 w-5/6" />}
          <Basis ids={basis} invalid={invalidBasis} />
        </div>
      </TableHead>
      <TableCell className="align-top whitespace-normal">
        {optimistic !== undefined && likely !== undefined && pessimistic !== undefined ? (
          <div className="flex flex-col gap-2 pt-2">
            <RangeBar optimistic={optimistic} likely={likely} pessimistic={pessimistic} max={max} />
            <span aria-hidden className="num flex flex-wrap gap-x-1 text-xs text-muted-foreground">
              <span className="whitespace-nowrap">{formatRange(optimistic, pessimistic)},</span>
              <span className="whitespace-nowrap">likely {formatHours(likely)}</span>
            </span>
          </div>
        ) : (
          <Pending className="mt-2 h-2 rounded-full" />
        )}
      </TableCell>
      <TableCell className="num text-right align-top font-medium">{expected !== undefined ? formatHours(expected) : <Pending className="ml-auto w-10" />}</TableCell>
    </TableRow>
  );
};

type Props = { items?: TaskView[]; streaming: boolean; invalidBasis: Set<string> };

export const TasksTable = ({ items, streaming, invalidBasis }: Props) => {
  const tasks = received(items, streaming);
  if (!tasks || tasks.length === 0)
    return <Section title="Tasks">{!tasks ? <EstimateSkeleton shape="table" /> : <Empty>No tasks.</Empty>}</Section>;
  // One scale for every bar, so the widths compare across rows.
  const max = Math.max(0, ...tasks.flatMap((t) => [t.optimistic_hours, t.likely_hours, t.pessimistic_hours]).filter((hours) => hours !== undefined));
  return (
    <Section title="Tasks">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="text-xs text-muted-foreground">Task</TableHead>
            <TableHead className="w-28 text-xs text-muted-foreground sm:w-44">Range</TableHead>
            <TableHead className="w-20 text-right text-xs text-muted-foreground">Expected</TableHead>
          </TableRow>
        </TableHeader>
        {(streaming ? byRun(tasks) : byPhase(tasks)).map(([phase, group], index) => {
          const subtotal = sum(group.map((task) => task.expected_hours));
          return (
            <TableBody key={index}>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead scope="rowgroup" colSpan={2} className="h-8 text-xs font-semibold">
                  {phase ? PHASE_LABELS[phase] : <Pending className="h-3 w-24" />}
                </TableHead>
                <TableCell className="num h-8 py-0 text-right text-xs font-medium">
                  {subtotal !== undefined ? formatHours(subtotal) : <Pending className="ml-auto h-3 w-10" />}
                </TableCell>
              </TableRow>
              {group.map((task, i) => (
                <TaskRow key={i} task={task} max={max} invalidBasis={task.id !== undefined && invalidBasis.has(task.id)} />
              ))}
            </TableBody>
          );
        })}
      </Table>
    </Section>
  );
};
