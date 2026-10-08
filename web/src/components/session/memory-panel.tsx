import { type ReactNode, useId } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { components } from "@/lib/ai-service/schema";

type Field = keyof components["schemas"]["ProjectMetadata"];
type Props = {
  metadata?: unknown; // the session's facts, unchecked wire data; undefined until the session is known
  changed?: readonly string[]; // the fields the latest completed turn changed (`metadata_changes`)
};

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" && value.trim() ? value : undefined);
const count = (value: unknown) => (Number.isInteger(value) && Number(value) > 0 ? Number(value) : undefined);
const texts = (value: unknown) => (Array.isArray(value) ? value.map(text).filter((item) => item !== undefined) : []);

const Unknown = () => <span className="text-muted-foreground">Not mentioned yet</span>;

// The badge sits in the term, so it is read with the fact's name ("Technologies Updated").
const Fact = ({ label, updated, children }: { label: string; updated: boolean; children: ReactNode }) => (
  <div className="flex flex-col gap-1">
    <dt className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
      <span>{label}</span>
      {updated && (
        <Badge variant="outline" className="font-normal text-foreground">
          Updated
        </Badge>
      )}
    </dt>
    <dd className="text-sm wrap-anywhere">{children}</dd>
  </div>
);

const Loading = () => (
  <div aria-busy="true" className="flex flex-col gap-4">
    {[0, 1, 2, 3].map((i) => (
      <div key={i} className="flex flex-col gap-1.5">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-5 w-full" />
      </div>
    ))}
  </div>
);

// What the session remembers apart from the history (spec §7.3): the four facts the AI service merges after each turn
// and sends with every prompt. A fact the latest turn changed carries a subtle "Updated" badge.
export const MemoryPanel = ({ metadata, changed = [] }: Props) => {
  const headingId = useId();
  const facts = isObject(metadata) ? metadata : {};
  const updated = (field: Field) => changed.includes(field);
  const name = text(facts.project_name);
  const team = count(facts.assumed_team_size);
  const technologies = texts(facts.mentioned_technologies);
  const scope = text(facts.agreed_scope);
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <h2 id={headingId} className="text-sm font-semibold">
        Project memory
      </h2>
      {metadata === undefined ? (
        <Loading />
      ) : (
        <dl className="flex flex-col gap-4">
          <Fact label="Project name" updated={updated("project_name")}>
            {name ?? <Unknown />}
          </Fact>
          <Fact label="Team size" updated={updated("assumed_team_size")}>
            {team ? <span className="num">{`${team} ${team === 1 ? "person" : "people"}`}</span> : <Unknown />}
          </Fact>
          <Fact label="Technologies" updated={updated("mentioned_technologies")}>
            {technologies.length ? (
              <ul role="list" className="flex flex-wrap gap-1.5">
                {technologies.map((technology, i) => (
                  <li key={i}>
                    <Badge variant="secondary" className="font-normal">
                      {technology}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <Unknown />
            )}
          </Fact>
          <Fact label="Agreed scope" updated={updated("agreed_scope")}>
            {scope ? <p className="text-sm">{scope}</p> : <Unknown />}
          </Fact>
        </dl>
      )}
    </section>
  );
};
