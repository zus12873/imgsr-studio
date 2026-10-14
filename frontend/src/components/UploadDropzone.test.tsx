import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UploadDropzone } from "./UploadDropzone";

const png = () => new File(["x"], "a.png", { type: "image/png" });

function paste(file: File) {
  const event = new Event("paste");
  Object.defineProperty(event, "clipboardData", { value: { files: [file] } });
  window.dispatchEvent(event);
}

test("choosing a file calls onFile", async () => {
  const onFile = vi.fn();
  render(<UploadDropzone onFile={onFile} />);
  await userEvent.upload(screen.getByTestId("file-input"), png());
  expect(onFile).toHaveBeenCalledWith(expect.objectContaining({ name: "a.png" }));
});

test("pasting an image calls onFile", () => {
  const onFile = vi.fn();
  render(<UploadDropzone onFile={onFile} />);
  paste(png());
  expect(onFile).toHaveBeenCalledTimes(1);
});

test("dropping a file calls onFile", () => {
  const onFile = vi.fn();
  render(<UploadDropzone onFile={onFile} />);
  fireEvent.drop(screen.getByRole("button", { name: /拖入、粘贴或点击/ }), {
    dataTransfer: { files: [png()] },
  });
  expect(onFile).toHaveBeenCalledTimes(1);
});

test("a disabled dropzone ignores paste and drop", () => {
  const onFile = vi.fn();
  render(<UploadDropzone onFile={onFile} disabled />);
  paste(png());
  fireEvent.drop(screen.getByRole("button", { name: /拖入、粘贴或点击/ }), {
    dataTransfer: { files: [png()] },
  });
  expect(onFile).not.toHaveBeenCalled();
});
