/* Run against tests/_dashboard_atlas_fixture.py. All declarations are pending UI test inputs. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
(async () => {
  const [url, output] = process.argv.slice(2);
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL
      ? { channel: process.env.PLAYWRIGHT_CHANNEL }
      : {}),
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1600, height: 1050 },
      permissions: ["clipboard-read", "clipboard-write"],
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const actual = await (await page.request.get(url + "/api/snapshot")).json();
    await page.goto(url);
    await page.locator(".action").waitFor();
    await page.locator('#nav [data-view="outcomes"]').click();
    await page.locator('[data-question="q2"]').click();
    assert.equal(
      await page.locator(".result-table .number").textContent(),
      "0",
    );
    assert.ok(
      await page.getByText("探索结果 · 已选执行", { exact: true }).isVisible(),
    );
    await page.locator(".figure-sheet img").waitFor();
    await page.waitForFunction(
      () => document.querySelector(".figure-sheet img")?.naturalWidth > 0,
    );
    await page.screenshot({
      path: path.join(output, "question-outcomes.png"),
      scale: "css",
    });
    await page
      .locator('[data-id="FIG-Q2-MECHANISM"][data-kind="figure"]')
      .click();
    await page
      .getByRole("button", { name: "复制完整 prompt", exact: true })
      .click();
    const prompt = actual.figures.find(
      (f) => f.figure_id === "FIG-Q2-MECHANISM",
    ).prompt;
    assert.equal(
      (await page.evaluate(() => navigator.clipboard.readText())).replace(
        /\r\n/g,
        "\n",
      ),
      prompt.replace(/\r\n/g, "\n"),
    );
    await page.screenshot({
      path: path.join(output, "generation-prompt.png"),
      scale: "css",
    });
    await page.locator('[data-question="unlinked"]').click();
    assert.equal(await page.locator(".figure-tile").count(), 1); // tutorial FIG-Q2 has no declared link
    await page.locator('[data-question="q2"]').click();
    await page.locator('[data-outcome-tab="figures"]').click();
    assert.equal(await page.locator(".result-table").count(), 0);
    assert.equal(await page.locator(".figure-tile").count(), 2);
    await page.locator('[data-kind="figure"][data-id="FIG-Q2-CURVE"]').click();
    assert.equal(
      await page.locator('#inspector [data-atlas-copy="prompt"]').count(),
      0,
    );
    await page.waitForFunction(
      () => document.querySelector(".gallery-large img")?.naturalWidth > 0,
    );
    await page.screenshot({
      path: path.join(output, "figure-preview.png"),
      scale: "css",
    });
    await page.locator("#theme").click();
    await page.screenshot({
      path: path.join(output, "outcomes-dark.png"),
      scale: "css",
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: path.join(output, "outcomes-mobile.png"),
      scale: "css",
    });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    assert.deepEqual(errors, []);
    console.log(
      "Atlas browser passed: actual result, question filters, data preview, full prompt clipboard, route boundary, dark and mobile.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
