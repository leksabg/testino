// Render an HTML file to PDF with the preinstalled Playwright Chromium.
// usage: node render.js <input.html> <output.pdf>
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const [input, output] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 794, height: 1123 } });
  await page.goto('file://' + path.resolve(input), { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.emulateMedia({ media: 'print' });

  // QA: report clipped code blocks and an overflowing cover
  const issues = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('pre.code').forEach((el, i) => {
      if (el.scrollWidth > el.clientWidth + 1) out.push(`pre.code #${i} clipped horizontally (${el.scrollWidth} > ${el.clientWidth})`);
    });
    const cover = document.querySelector('.cover');
    if (cover && cover.scrollHeight > cover.clientHeight + 1) out.push(`cover overflows (${cover.scrollHeight} > ${cover.clientHeight})`);
    return out;
  });
  issues.forEach((m) => console.log('QA:', m));

  await page.pdf({ path: output, preferCSSPageSize: true, printBackground: true, outline: true, tagged: true });
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
