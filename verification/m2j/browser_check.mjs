import { writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const baseUrl = process.env.M2J_BASE_URL ?? 'http://127.0.0.1:8776'
const browser = await chromium.launch({ channel: 'chrome', headless: true })

try {
  const desktop = await exercise({ width: 1440, height: 900 }, 'desktop-1440x900')
  const mobile = await exercise({ width: 390, height: 844 }, 'mobile-390x844')
  let trace = await fetch(`${baseUrl}/__scenario__/trace`).then((response) => response.json())
  const threadId = trace.named_resolutions.at(-1)?.thread_id
  if (typeof threadId !== 'string') throw new Error('fixture did not record a resolved thread')
  const refused = await fetch(`${baseUrl}/v1/rack/parameters`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      module_id: 'chat',
      thread_id: threadId,
      parameter_id: 'model.temperature',
      value: 1.5,
    }),
  })
  if (refused.status !== 403) throw new Error(`unbound module write returned ${refused.status}`)
  trace = await fetch(`${baseUrl}/__scenario__/trace`).then((response) => response.json())
  if (!trace.events.some((event) => event.type === 'parameter.refused' && event.payload?.reason === 'unbound')) {
    throw new Error('unbound module refusal was not durably journaled')
  }
  const evidence = { fixture: 'M2J REGRESSION', base_url: baseUrl, desktop, mobile, trace }
  await writeFile(join(evidenceDir, 'rendered.json'), `${JSON.stringify(evidence, null, 2)}\n`)
  console.log(`M2J rendered PASS: ${join(evidenceDir, 'rendered.json')}`)
} finally {
  await browser.close()
}

async function exercise(viewport, suffix) {
  const context = await browser.newContext({ viewport, screen: viewport })
  const page = await context.newPage()
  try {
    await page.goto(`${baseUrl}/?fixture=M2J%20REGRESSION`, { waitUntil: 'domcontentloaded' })
    await page.getByText('M2J REGRESSION FIXTURE', { exact: true }).waitFor()
    const chat = page.frameLocator('iframe[src*="rack_module=chat"]')
    await chat.getByRole('button', { name: /Active model:/ }).click()
    const device = page.frameLocator('iframe[src*="rack_module=model_device"]')
    await device.getByRole('heading', { name: 'Model device' }).waitFor()
    await device.getByTestId('model-device-resolved').getByText('openrouter:fixture/base').waitFor()

    await device.getByRole('slider', { name: 'Temperature' }).press('ArrowRight')
    await device.locator('[data-parameter-id="model.temperature"] output').getByText('0.05', { exact: true }).waitFor()
    await waitForHistoryLength(device, 1)
    await device.getByRole('combobox', { name: 'Reasoning effort' }).selectOption('high')
    await waitForHistoryLength(device, 2)
    await device.getByRole('textbox', { name: 'OpenRouter model' }).fill('openrouter:fixture/next')
    await device.getByRole('button', { name: 'Resolve', exact: true }).click()
    await device.getByTestId('model-device-resolved').getByText('openrouter:fixture/next').waitFor()
    await chat.getByRole('button', { name: 'Active model: openrouter:fixture/next' }).waitFor()
    await page.screenshot({ path: join(evidenceDir, `01-live-${suffix}.png`) })

    await device.getByRole('slider', { name: 'Control history' }).press('Home')
    await device.getByTestId('model-device-resolved').getByText('openrouter:fixture/base').waitFor()
    await device.getByText('Inherit', { exact: true }).first().waitFor()
    await page.screenshot({ path: join(evidenceDir, `02-history-${suffix}.png`) })

    await device.getByRole('button', { name: 'Defaults' }).click()
    if (!(await device.getByRole('textbox', { name: 'OpenRouter model' }).isDisabled())) {
      throw new Error('GLOBAL defaults scope allowed a thread write')
    }
    const overflow = await device.locator('html').evaluate((root) =>
      root.scrollWidth > root.clientWidth
    )
    if (overflow) throw new Error(`model device overflowed ${viewport.width}px viewport`)
    return {
      viewport,
      resolved_model: 'openrouter:fixture/next',
      header_synchronized: true,
      temperature_journaled: true,
      effort_journaled: true,
      historical_replay: true,
      defaults_read_only: true,
      horizontal_overflow: false,
    }
  } finally {
    await context.close()
  }
}

async function waitForHistoryLength(device, expected) {
  const history = device.getByRole('slider', { name: 'Control history' })
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    if (Number(await history.getAttribute('max')) >= expected) return
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  throw new Error(`parameter history did not reach ${expected} accepted changes`)
}
