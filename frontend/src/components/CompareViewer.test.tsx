import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CompareViewer } from "./CompareViewer";

const props = { left: { src: "/a.png", label: "原图" }, right: { src: "/b.png", label: "第 1 轮" } };

test("slider mode overlays the left image clipped at the slider position", () => {
  render(<CompareViewer {...props} />);
  const overlay = screen.getByAltText("原图");
  expect(overlay.style.clipPath).toBe("inset(0 50% 0 0)");
  fireEvent.change(screen.getByLabelText("对比位置"), { target: { value: "30" } });
  expect(overlay.style.clipPath).toBe("inset(0 70% 0 0)");
  expect(screen.getByAltText("第 1 轮")).toBeInTheDocument();
});

test("side-by-side mode shows both images with captions", async () => {
  render(<CompareViewer {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "并排（同步缩放）" }));
  expect(screen.getByRole("button", { name: "并排（同步缩放）" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("原图", { selector: "figcaption" })).toBeInTheDocument();
  expect(screen.getByText("第 1 轮", { selector: "figcaption" })).toBeInTheDocument();
});
