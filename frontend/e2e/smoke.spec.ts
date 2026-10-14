import { expect, test } from "@playwright/test";

const file = "e2e/fixtures/sample.png"; // relative to frontend/, where `npm run e2e` runs

test("logged-in flow: upload → confirm → generate → accept → download", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("用户名").fill("admin");
  await page.getByLabel("密码").fill("password123");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "工作台" })).toBeVisible();
  await page.getByTestId("file-input").setInputFiles(file);
  await expect(page.getByLabel("原文")).toHaveValue("示例原文。", { timeout: 20_000 });
  await page.getByRole("button", { name: "确认原文" }).click();
  await page.getByRole("button", { name: "开始生成" }).click();
  await page.getByRole("button", { name: "设为最终版" }).click({ timeout: 20_000 });
  await expect(page.getByText("已定稿").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "下载" })).toHaveAttribute("href", /download-1\?download=1$/);
});

test("guest flow on a phone-sized screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/guest");
  await expect(page.getByText(/今日剩余 3 次/)).toBeVisible();
  await page.getByTestId("file-input").setInputFiles(file);
  await expect(page.getByRole("link", { name: "下载" })).toBeVisible({ timeout: 20_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
