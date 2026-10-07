import { Chat } from "@/components/chat/chat";
import { loadSamples } from "@/lib/samples";

export default async function Home() {
  return <Chat samples={await loadSamples()} />;
}
