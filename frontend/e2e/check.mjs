// Uses the real backend/PDF; only /api/chat is mocked. Never measures LLM quality.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const base = process.env.APP_URL || 'http://127.0.0.1:8010'
const output = fileURLToPath(new URL('../../data/browser-checks/', import.meta.url))
const answer = await fs.readFile(new URL('../../data/browser-answer.json', import.meta.url), 'utf8')
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE || undefined })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))

try {
  await page.goto(base)
  await page.getByRole('heading', { name: 'Ask the filing.' }).waitFor()
  await page.screenshot({ path: `${output}/desktop.png`, fullPage: true })
  await page.getByRole('button', { name: 'Read the filing' }).click()
  await page.waitForFunction(() => {
    const canvas = document.querySelector('canvas')
    return canvas && canvas.width > 100 && !document.querySelector('.pdf-loading')
  })
  assert.equal(await page.locator('.pdf-error').count(), 0)
  await page.getByLabel('PDF page', { exact: true }).fill('31')
  await page.getByLabel('PDF page', { exact: true }).press('Enter')
  await page.locator('canvas[aria-label^="PDF page 31."]').waitFor()
  await page.waitForFunction(() => !document.querySelector('.pdf-loading'))
  await page.screenshot({ path: `${output}/document-page-31.png`, fullPage: true })

  let chatCalls = 0
  await page.route('**/api/chat', async route => {
    const payload = route.request().postDataJSON()
    assert.deepEqual(Object.keys(payload), ['query'])
    chatCalls++
    if (chatCalls === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { message: 'Simulated temporary outage.' }, request_id: 'browser-retry' }) })
    return route.fulfill({ status: 200, contentType: 'application/json', body: answer })
  })
  await page.getByLabel('Ask a question about the filing').fill('What were total net sales in 2023?')
  await page.getByLabel('Send question', { exact: true }).click()
  await page.getByText('Simulated temporary outage.').waitFor()
  await page.getByRole('button', { name: 'Try again' }).click()
  await page.getByText('Apple reported total net sales of $383,285 million for fiscal 2023.').waitFor()
  assert.equal(chatCalls, 2)
  assert.equal(await page.locator('.turn').count(), 1)
  await page.getByLabel('View source 1, PDF page 31', { exact: true }).click()
  await page.getByRole('heading', { name: 'CONSOLIDATED STATEMENTS OF OPERATIONS' }).waitFor()
  await page.waitForFunction(() => document.querySelectorAll('.pdf-highlight').length > 0 && !document.querySelector('.pdf-loading'))
  await page.getByRole('button', { name: 'Show text excerpt' }).click()
  assert.match(await page.locator('.source-excerpt').innerText(), /Total net sales 383,285 394,328 365,817/)
  await page.getByRole('button', { name: 'Hide text excerpt' }).click()
  await page.screenshot({ path: `${output}/citation.png`, fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => {
    const viewer = document.querySelector('.pdf-viewer')
    const canvas = document.querySelector('canvas')
    return viewer && canvas && Math.abs(canvas.clientWidth - (viewer.clientWidth - 32)) < 2 &&
      !document.querySelector('.pdf-loading') && document.querySelectorAll('.pdf-highlight').length > 0
  })
  await page.screenshot({ path: `${output}/mobile-source.png`, fullPage: true })
  await page.getByRole('complementary', { name: 'Document and sources' }).getByLabel('Close source panel', { exact: true }).click()
  assert.equal(await page.locator('.source-panel').isVisible(), false)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  assert.equal(overflow, false, 'Mobile layout must not overflow horizontally')
  const composer = await page.locator('.composer').boundingBox()
  console.log('Mobile composer geometry:', composer)
  assert.ok(composer && composer.y >= 0 && composer.y + composer.height <= 844, 'Mobile composer must remain visible')
  await page.screenshot({ path: `${output}/mobile-chat.png`, fullPage: true })
  await page.getByRole('button', { name: 'New chat' }).click()
  await page.getByRole('heading', { name: 'Ask the filing.' }).waitFor()
  await page.screenshot({ path: `${output}/mobile-home.png`, fullPage: true })
  assert.deepEqual(errors, [], 'No uncaught browser exceptions')
  console.log('Browser checks passed: document rendering, page navigation, retry, cited answer, PDF highlights, mobile drawer, new chat. Chat response was mocked.')
} finally {
  await browser.close()
}
