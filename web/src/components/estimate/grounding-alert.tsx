import { TriangleAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { GroundingChecks } from "@/lib/estimate/read";

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export const GroundingAlert = ({ grounding: { ungrounded, invalidBasis } }: { grounding: GroundingChecks }) => {
  const problems = [
    ungrounded.size > 0 && `${count(ungrounded.size, "requirement has", "requirements have")} no matching quote in the transcript`,
    invalidBasis.size > 0 && `${count(invalidBasis.size, "task has", "tasks have")} no valid basis`,
  ].filter((problem) => problem !== false);
  if (problems.length === 0) return null;
  return (
    // Not a live region: the view announces completion once, and this sits in the content that announcement points to.
    <Alert role={undefined} className="border-ungrounded/40 bg-ungrounded-subtle">
      <TriangleAlert className="text-ungrounded" />
      <AlertTitle className="text-ungrounded">Review before sharing</AlertTitle>
      <AlertDescription className="text-foreground">{`${problems.join(" and ")}.`}</AlertDescription>
    </Alert>
  );
};
