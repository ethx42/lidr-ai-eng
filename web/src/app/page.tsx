import { Workspace } from "@/components/workspace/workspace";
import { loadSamples } from "@/lib/samples";

export default async function Home() {
  return <Workspace samples={await loadSamples()} />;
}
