import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";

export type Sample = { id: string; title: string; description: string; text: string };

// Byte-identical copies of the eval sources (tests/test_web_samples.py), so replay cassettes match them.
const SAMPLES: Omit<Sample, "text">[] = [
  { id: "course-meeting", title: "Course meeting", description: "Fitness studio chain: booking app, staff panel and payments." },
  { id: "clinic-portal", title: "Clinic portal", description: "Physiotherapy patient portal on top of an existing system." },
  { id: "vague-marketplace", title: "Vague marketplace", description: "An early idea with few details, so expect low confidence." },
];

const DIRECTORY = path.join(process.cwd(), "src", "content", "samples");

// Read by the page (a Server Component) when it prerenders; client components get the text as props.
export const loadSamples = () =>
  Promise.all(SAMPLES.map(async (sample) => ({ ...sample, text: await readFile(path.join(DIRECTORY, `${sample.id}.md`), "utf8") })));
