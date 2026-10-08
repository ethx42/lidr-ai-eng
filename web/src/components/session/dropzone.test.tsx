import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Dropzone } from "./dropzone";

const pdf = (name = "spec.pdf", size = 8) => new File([new Uint8Array(size)], name, { type: "application/pdf" });

// The composer's use: the parent owns the list.
const Controlled = ({ maxFiles = 5, maxBytes = 1024, initial = [] }: { maxFiles?: number; maxBytes?: number; initial?: File[] }) => {
  const [files, setFiles] = useState<File[]>(initial);
  return <Dropzone maxFiles={maxFiles} maxBytes={maxBytes} files={files} onChange={setFiles} />;
};
const chips = () => within(screen.getByRole("list", { name: "Attached documents" })).queryAllByRole("listitem");

describe("Dropzone", () => {
  it("rejects unsupported and oversize files with a visible reason, keeps valid ones", async () => {
    const onChange = vi.fn();
    render(<Dropzone maxFiles={5} maxBytes={1024} onChange={onChange} />);
    const input = screen.getByLabelText(/attach documents/i);
    // applyAccept defaults to true in user-event 14 and would drop virus.exe before the component sees it
    await userEvent.setup({ applyAccept: false }).upload(input, [
      new File(["%PDF-1.7"], "spec.pdf", { type: "application/pdf" }),
      new File(["x"], "virus.exe", { type: "application/octet-stream" }),
      new File([new Uint8Array(2048)], "big.txt", { type: "text/plain" }),
    ]);
    expect(onChange).toHaveBeenLastCalledWith([expect.objectContaining({ name: "spec.pdf" })]);
    expect(screen.getByText(/virus\.exe.*not supported/i)).toBeVisible();
    expect(screen.getByText(/big\.txt.*too large/i)).toBeVisible();
  });

  it("accepts .pdf, .docx and .txt, in any case and whatever type the browser reports", async () => {
    const onChange = vi.fn();
    render(<Dropzone maxFiles={5} maxBytes={1024} onChange={onChange} />);
    const input = screen.getByLabelText(/attach documents/i);
    expect(input).toHaveAttribute("accept", ".pdf,.docx,.txt");
    expect(input).toHaveAttribute("multiple");
    await userEvent.setup({ applyAccept: false }).upload(input, [pdf("A.PDF"), new File(["x"], "brief.docx", { type: "" }), new File(["x"], "notes.txt", { type: "" })]);
    expect(onChange.mock.lastCall?.[0].map((file: File) => file.name)).toEqual(["A.PDF", "brief.docx", "notes.txt"]);
  });

  it("shows each attached file as a chip with its size, and refuses empty files, duplicates and more than the limit", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<Controlled maxFiles={2} maxBytes={4 * 1024 * 1024} />);
    const input = screen.getByLabelText(/attach documents/i);
    const spec = pdf("spec.pdf", 1536);
    await user.upload(input, [spec]);
    expect(chips()).toHaveLength(1);
    expect(within(chips()[0]).getByTitle("spec.pdf")).toHaveTextContent("spec.pdf");
    expect(within(chips()[0]).getByText("1.5 KB")).toBeInTheDocument();
    expect(within(chips()[0]).getByRole("button", { name: "Remove spec.pdf" })).toBeInTheDocument();

    await user.upload(input, [spec, new File([], "empty.txt", { type: "text/plain" }), pdf("plan.pdf", 2 * 1024 * 1024), pdf("third.pdf")]);
    expect(chips().map((chip) => within(chip).getByTitle(/\.pdf$/).textContent)).toEqual(["spec.pdf", "plan.pdf"]);
    expect(within(chips()[1]).getByText("2 MB")).toBeInTheDocument();
    const reasons = screen.getByRole("status");
    expect(reasons).toHaveTextContent("spec.pdf is already attached.");
    expect(reasons).toHaveTextContent("empty.txt is empty.");
    expect(reasons).toHaveTextContent("third.pdf was not added: up to 2 files per message.");
  });

  it("removes a file from its chip and moves focus to the next control, never to the page", async () => {
    const user = userEvent.setup();
    render(<Controlled initial={[pdf("a.pdf"), pdf("b.pdf")]} />);
    await user.click(screen.getByRole("button", { name: "Remove a.pdf" }));
    expect(chips()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Remove b.pdf" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Remove b.pdf" }));
    expect(screen.queryByRole("list", { name: "Attached documents" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Attach documents" })).toHaveFocus();
  });

  it("opens the file picker from its button, and clears the reasons on the next choice", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<Controlled />);
    const input = screen.getByLabelText(/attach documents/i);
    const click = vi.spyOn(input, "click");
    await user.click(screen.getByRole("button", { name: "Attach documents" }));
    expect(click).toHaveBeenCalled();

    await user.upload(input, [new File(["x"], "virus.exe")]);
    expect(screen.getByRole("status")).toHaveTextContent("virus.exe is not supported");
    await user.upload(input, [pdf()]);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(input).toHaveValue(""); // the same file can be chosen again
  });

  it("takes dropped files, highlighting while they are dragged over", () => {
    const onChange = vi.fn();
    render(<Dropzone maxFiles={5} maxBytes={1024} onChange={onChange} />);
    const zone = screen.getByText(/or drop them here/i).closest("[data-slot=dropzone]");
    if (!(zone instanceof HTMLElement)) throw new Error("no drop zone");
    const dataTransfer = { files: [pdf()], types: ["Files"] };
    fireEvent.dragEnter(zone, { dataTransfer });
    fireEvent.dragOver(zone, { dataTransfer });
    expect(zone).toHaveAttribute("data-dragging");
    fireEvent.drop(zone, { dataTransfer });
    expect(zone).not.toHaveAttribute("data-dragging");
    expect(onChange).toHaveBeenLastCalledWith([expect.objectContaining({ name: "spec.pdf" })]);
  });

  it("says what it accepts", () => {
    render(<Dropzone maxFiles={5} maxBytes={10 * 1024 * 1024} onChange={vi.fn()} />);
    expect(screen.getByText("PDF, DOCX or TXT, up to 5 files of 10 MB each")).toBeInTheDocument();
  });
});
