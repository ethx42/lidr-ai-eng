import { received } from "@/lib/estimate/read";
import { EstimateSkeleton } from "./estimate-skeleton";
import { Empty, Section } from "./section";

export const OpenQuestions = ({ items, streaming }: { items?: string[]; streaming: boolean }) => {
  const questions = received(items, streaming);
  return (
    <Section title="Open questions" description="Ask the client before committing to these numbers.">
      {!questions ? (
        <EstimateSkeleton shape="list" count={2} />
      ) : questions.length === 0 ? (
        <Empty>No open questions.</Empty>
      ) : (
        <ul className="flex list-disc flex-col gap-2 pl-5 text-sm wrap-anywhere marker:text-muted-foreground">
          {questions.map((question, i) => (
            <li key={i}>{question}</li>
          ))}
        </ul>
      )}
    </Section>
  );
};
