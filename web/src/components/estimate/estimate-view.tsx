import type { components } from "@/lib/ai-service/schema";
import { type EstimateModel, readEstimate, readGrounding, received } from "@/lib/estimate/read";
import type { PartialBreakdown } from "@/lib/estimate/types";
import { ConfidenceBadge } from "./confidence-badge";
import { EstimateSkeleton, Pending } from "./estimate-skeleton";
import { GroundingAlert } from "./grounding-alert";
import { OpenQuestions } from "./open-questions";
import { RequirementsList } from "./requirements-list";
import { Empty, Section } from "./section";
import { TasksTable } from "./tasks-table";
import { TeamAndRisks } from "./team-and-risks";
import { TotalsStrip } from "./totals-strip";

type Schemas = components["schemas"];
type Props = {
  data: PartialBreakdown | Schemas["EnrichedBreakdown"];
  grounding?: Schemas["GroundingReport"];
  streaming: boolean;
  // this snapshot is the result of a stream that just completed (not an earlier estimate kept after a stop or failure)
  completed?: boolean;
  activeRequirement?: string;
  onRequirementFocus?: (id: string | null) => void;
  pinFor?: (id: string) => (() => void) | undefined;
  evidenceNote?: (id: string) => string | undefined;
};

const Assumptions = ({ items, streaming }: { items?: EstimateModel["assumptions"]; streaming: boolean }) => {
  const assumptions = received(items, streaming);
  return (
    <Section title="Assumptions">
      {!assumptions ? (
        <EstimateSkeleton shape="list" count={2} />
      ) : assumptions.length === 0 ? (
        <Empty>No assumptions.</Empty>
      ) : (
        <ul role="list" className="flex flex-col">
          {assumptions.map(({ id, statement, impact_if_wrong: impact }, i) => (
            <li key={i} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-3 border-b py-2">
              <span className="font-mono text-xs leading-5 text-muted-foreground">{id ?? <Pending className="mt-1 h-3 w-6" />}</span>
              <div className="flex min-w-0 flex-col gap-1 wrap-anywhere">
                {statement ? <p className="text-sm">{statement}</p> : <Pending className="w-4/5" />}
                {impact ? <p className="text-xs text-muted-foreground">If wrong: {impact}</p> : <Pending className="h-3 w-3/5" />}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
};

// Renders any snapshot: every value is read through a guard, and whatever is missing shows as a skeleton.
// While streaming the article is `aria-busy` and nothing inside it is live; one polite region announces completion.
export const EstimateView = ({ data, grounding, streaming, completed = false, activeRequirement, onRequirementFocus, pinFor, evidenceNote }: Props) => {
  const estimate = readEstimate(data);
  const checks = readGrounding(grounding);
  const ready = completed && estimate.totals !== undefined;
  return (
    <article aria-busy={streaming} className="group/estimate flex min-w-0 flex-col gap-8">
      <header className="flex flex-col gap-3">
        {estimate.project_name ? (
          <h2 className="text-2xl font-semibold text-balance">{estimate.project_name}</h2>
        ) : (
          <>
            <h2 className="sr-only">Estimate</h2>
            <Pending className="h-8 w-64 max-w-full" />
          </>
        )}
        <TotalsStrip totals={estimate.totals} />
      </header>
      <GroundingAlert grounding={checks} />
      <Section title="Summary">
        {estimate.summary ? <p className="max-w-prose text-sm">{estimate.summary}</p> : <EstimateSkeleton shape="paragraph" />}
      </Section>
      <RequirementsList
        items={estimate.requirements}
        streaming={streaming}
        ungrounded={checks.ungrounded}
        activeRequirement={activeRequirement}
        onRequirementFocus={onRequirementFocus}
        pinFor={pinFor}
        evidenceNote={evidenceNote}
      />
      <Assumptions items={estimate.assumptions} streaming={streaming} />
      <OpenQuestions items={estimate.open_questions} streaming={streaming} />
      <TasksTable items={estimate.tasks} streaming={streaming} invalidBasis={checks.invalidBasis} />
      <TeamAndRisks team={estimate.team} risks={estimate.risks} streaming={streaming} />
      <Section title="Confidence">
        <div className="flex flex-col items-start gap-2">
          {estimate.confidence ? <ConfidenceBadge level={estimate.confidence} /> : <Pending className="h-5 w-32 rounded-4xl" />}
          {estimate.confidence_rationale ? (
            <p className="max-w-prose text-sm">{estimate.confidence_rationale}</p>
          ) : (
            <div className="w-full">
              <EstimateSkeleton shape="paragraph" count={2} />
            </div>
          )}
        </div>
      </Section>
      <p role="status" aria-live="polite" className="sr-only">
        {ready ? "Estimate ready" : ""}
      </p>
    </article>
  );
};
