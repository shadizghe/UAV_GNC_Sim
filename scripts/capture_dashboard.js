/* Capture static panel screenshots + a sequence of replay frames for the
 * README gallery and looping demo GIF. Requires the Docker stack running
 * (`docker compose up -d`) and Playwright installed (`npm i playwright`).
 *
 * Outputs:
 *   docs/img/dashboard-landing.png
 *   docs/img/panel-tactical.png
 *   docs/img/panel-sim-room.png
 *   docs/img/panel-monte-carlo.png
 *   docs/img/_frames/frame_NNN.png   ← stitched into demo.gif by the
 *                                      sibling scripts/build_demo_gif.py
 */
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const OUT = (name) => path.resolve(__dirname, "..", "docs", "img", name);
const FRAMES_DIR = OUT("_frames");

async function clickTab(page, label) {
  const btn = page.getByRole("button", { name: new RegExp(`^${label}$`, "i") });
  await btn.first().click();
  // Tab transitions render new panels; give them a beat to settle.
  await page.waitForTimeout(900);
}

(async () => {
  fs.mkdirSync(FRAMES_DIR, { recursive: true });

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.warn("[page]", e.message));

  await page.goto("http://localhost:3005", { waitUntil: "domcontentloaded" });
  // The 3D canvas mounts after the dynamic import + WebGL boot — give it
  // a generous window. ``networkidle`` is unreliable here because the
  // dashboard polls a few endpoints in the background.
  await page.waitForSelector("canvas", { timeout: 60000 });
  // Wait for the Suspense fallback ("Initialising scene...") to disappear
  // so screenshots capture the rendered Three.js scene rather than the
  // loading HUD.
  await page.waitForFunction(
    () => !Array.from(document.querySelectorAll("div"))
      .some((d) => /initialising scene/i.test(d.textContent || "")),
    { timeout: 30000 },
  ).catch(() => {});
  await page.waitForTimeout(2500);

  // 1) Landing on the default Mission tab.
  await page.screenshot({ path: OUT("dashboard-landing.png") });
  console.log("wrote", OUT("dashboard-landing.png"));

  // 2) Tactical map.
  await clickTab(page, "Tactical");
  await page.screenshot({ path: OUT("panel-tactical.png") });
  console.log("wrote", OUT("panel-tactical.png"));

  // 3) Sim Room.
  await clickTab(page, "Sim Room");
  await page.screenshot({ path: OUT("panel-sim-room.png") });
  console.log("wrote", OUT("panel-sim-room.png"));

  // 4) Monte Carlo.
  await clickTab(page, "Monte Carlo");
  await page.screenshot({ path: OUT("panel-monte-carlo.png") });
  console.log("wrote", OUT("panel-monte-carlo.png"));

  // 5) Switch back to the default Mission tab so the next dev-session
  //    starts clean.
  await clickTab(page, "Mission");

  await browser.close();
})().catch((err) => { console.error(err); process.exit(1); });
