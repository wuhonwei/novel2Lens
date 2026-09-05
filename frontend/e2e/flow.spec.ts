import { test, expect } from "@playwright/test";

test("list, open 青川渡, tabs, settings, assets upload, export, back, create, delete", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/");
  await expect(page.getByTestId("btn-create")).toBeVisible();

  const openBtn = page.getByTestId("btn-open-青川渡");
  await expect(openBtn).toBeVisible({ timeout: 120_000 });
  await openBtn.click();
  await expect(page.getByRole("button", { name: /雾锁渡口/ })).toBeVisible();
  await expect(page.getByTestId("coach-panel")).toBeVisible();

  await page.getByRole("button", { name: "模型 / 画风" }).click();
  await page.getByTestId("btn-save-settings").click();
  await page.getByTestId("overwrite").check();
  await page.getByTestId("tab-全书资产").click();
  await page.getByTestId("tab-分镜").click();
  await expect(page.getByText("镜 1")).toBeVisible();
  await page.getByTestId("tab-原文").click();
  await page.getByTestId("tab-全书资产").click();
  await expect(page.getByTestId("btn-one-click-assets")).toBeVisible();
  await page.getByTestId("btn-view-character").click();
  await expect(page.getByTestId("section-人物形象")).toBeVisible();
  await page.getByTestId("btn-view-scene").click();
  await expect(page.getByTestId("section-核心场景")).toBeVisible();
  await page.getByTestId("btn-view-prop").click();
  await expect(page.getByTestId("section-核心物品")).toBeVisible();

  const fileInputs = page.locator('input[type="file"][accept="image/*"]');
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  if (await fileInputs.count()) {
    await fileInputs.first().setInputFiles({ name: "half.png", mimeType: "image/png", buffer: png });
  }

  page.once("dialog", (d) => d.accept());
  await page.getByTestId("btn-export").click();
  await page.getByTestId("btn-back").click();
  await expect(page.getByTestId("btn-create")).toBeVisible();

  await page.getByTestId("new-title").fill("按钮删除样例");
  await page.getByTestId("new-text").fill("第一章 测试\n只有一句。");
  await page.getByTestId("btn-create").click();
  await expect(page.getByText("第一章 测试")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("coach-panel")).toBeVisible();
  await page.getByTestId("btn-back").click();
  page.once("dialog", () => {});
  await page.getByTestId("btn-delete-按钮删除样例").click();
});
