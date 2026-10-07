import { Badge } from "@/components/ui/badge";
import { type EstimateModel, type Level, received } from "@/lib/estimate/read";
import { EstimateSkeleton, Pending } from "./estimate-skeleton";
import { Empty, Section } from "./section";

const IMPACT: Record<Level, { label: string; className: string }> = {
  high: { label: "High impact", className: "bg-danger-subtle text-danger" },
  medium: { label: "Medium impact", className: "bg-warning-subtle text-warning" },
  low: { label: "Low impact", className: "bg-secondary text-secondary-foreground" },
};

const Team = ({ items, streaming }: { items?: EstimateModel["team"]; streaming: boolean }) => {
  const team = received(items, streaming);
  return (
    <Section title="Team">
      {!team ? (
        <EstimateSkeleton shape="list" count={2} />
      ) : team.length === 0 ? (
        <Empty>No team suggested.</Empty>
      ) : (
        <ul role="list" className="flex flex-col text-sm">
          {team.map(({ role, count }, i) => (
            <li key={i} className="flex items-center justify-between gap-4 border-b py-2">
              {role ? <span className="min-w-0 wrap-anywhere">{role}</span> : <Pending className="w-32" />}
              {count !== undefined ? <span className="num font-medium">{count}</span> : <Pending className="w-4" />}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
};

const Risks = ({ items, streaming }: { items?: EstimateModel["risks"]; streaming: boolean }) => {
  const risks = received(items, streaming);
  return (
    <Section title="Risks">
      {!risks ? (
        <EstimateSkeleton shape="list" count={2} />
      ) : risks.length === 0 ? (
        <Empty>No risks identified.</Empty>
      ) : (
        <ul role="list" className="flex flex-col">
          {risks.map(({ description, impact, mitigation }, i) => (
            <li key={i} className="flex flex-col gap-2 border-b py-2 sm:grid sm:grid-cols-[7rem_minmax(0,1fr)] sm:gap-3">
              {impact ? (
                <Badge variant="secondary" className={IMPACT[impact].className}>
                  {IMPACT[impact].label}
                </Badge>
              ) : (
                <Pending className="h-5 w-20 rounded-4xl" />
              )}
              <div className="flex min-w-0 flex-col gap-1 wrap-anywhere">
                {description ? <p className="text-sm">{description}</p> : <Pending className="w-4/5" />}
                {mitigation ? <p className="text-xs text-muted-foreground">Mitigation: {mitigation}</p> : <Pending className="h-3 w-3/5" />}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
};

export const TeamAndRisks = ({ team, risks, streaming }: { team?: EstimateModel["team"]; risks?: EstimateModel["risks"]; streaming: boolean }) => (
  <div className="grid gap-8 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
    <Team items={team} streaming={streaming} />
    <Risks items={risks} streaming={streaming} />
  </div>
);
