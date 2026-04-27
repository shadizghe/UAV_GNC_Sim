/* Capture a hero screenshot of the running dashboard.
 * Usage:  node scripts/capture_dashboard.js
 * Requires the docker stack to be running (`docker compose up -d`).
 *
 * Produces docs/img/dashboard-landing.png — the mission planner landing
 * page, with the 3D scene, terrain, threat zones, and waypoint markers
 * visible. Use this as the README hero image.
 */
const { chromium } = require("playwright");
const path = require("path");

const OUT = (name) => path.resolve(__dirname, "..", "docs", "img", name);

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await ctx.newPage();
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  await page.waitForSelector("canvas", { timeout: 15000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: OUT("dashboard-landing.png"), fullPage: false });
  console.log("wrote", OUT("dashboard-landing.png"));
  await browser.close();
})().catch((err) => { console.error(err); process.exit(1); });
