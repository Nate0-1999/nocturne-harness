/** PLAN M2UX4 / B.6 r7: real rendered switching, seam resolution, persistence, and rim reflection. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const baseUrl = process.argv.includes('--base-url')
  ? process.argv[process.argv.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8807'
const fixtureUrl = `${baseUrl}/?fixture=${encodeURIComponent('M2UX4 REGRESSION')}`
const themes = ['neo-noir', 'seraph-dressed', 'gold-lines']
const expectedSeam = {
  'neo-noir': { user: 'rgb(201, 220, 228)', composerRgb: '7, 18, 27', lineRgb: '60, 210, 255' },
  'seraph-dressed': { user: 'rgb(238, 244, 251)', composerRgb: '7, 8, 15', lineRgb: '219, 229, 238' },
  'gold-lines': { user: 'rgb(38, 52, 82)', composerRgb: '245, 248, 252', lineRgb: '150, 104, 44' },
}
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
const consoleProblems = []
const pageErrors = []
const observations = {
  desktop: {},
  phone: {},
  phone_control_lane: null,
  seam: { desktop: {}, phone: {} },
  persistence: null,
  reflection: null,
}

page.on('console', (message) => {
  if (message.type() === 'error') consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))

try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(fixtureUrl, { waitUntil: 'domcontentloaded' })
  await waitForRack()
  console.log('M2UX4 step: rack ready')
  assertEqual(await page.getByTestId('theme-control').inputValue(), 'neo-noir', 'worn default')
  await chooseTheme('seraph-dressed', false)
  observations.reflection = await verifyReflectionSlide()
  await chooseTheme('neo-noir', false)
  await page.getByTestId('layout-reset').click()

  for (let index = 0; index < themes.length; index += 1) {
    const theme = themes[index]
    await chooseTheme(theme, false)
    observations.desktop[theme] = await renderedSeam(false)
    await page.screenshot({ path: join(evidenceDir, `0${index + 1}-${theme}-1280x900.png`) })
    if (theme === 'seraph-dressed') {
      const analysisStyles = await Promise.all(
        page.frames().map((target) => target.addStyleTag({ content: '.m2c-regression-fixture { visibility: hidden !important; }' })),
      )
      await page.screenshot({ path: join(evidenceDir, 'seraph-analysis-1280x900.png') })
      await Promise.all(analysisStyles.map((style) => style.evaluate((element) => element.remove())))
    }
    console.log(`M2UX4 step: desktop ${theme}`)
  }

  await page.setViewportSize({ width: 390, height: 844 })
  for (let index = 0; index < themes.length; index += 1) {
    const theme = themes[index]
    await chooseTheme(theme, false)
    const control = page.getByTestId('theme-control')
    if (!(await control.isVisible())) throw new Error(`theme control is not reachable at 390px for ${theme}`)
    observations.phone_control_lane ??= await verifyPhoneControlLane()
    observations.phone[theme] = await renderedSeam(false)
    await page.screenshot({ path: join(evidenceDir, `0${index + 4}-${theme}-390x844.png`) })
    console.log(`M2UX4 step: phone ${theme}`)
  }

  await page.setViewportSize({ width: 1280, height: 900 })
  await chooseTheme('neo-noir', false)
  await sendSeamPrompt()
  console.log('M2UX4 step: seam prompt rendered')
  for (const theme of themes) {
    await chooseTheme(theme)
    observations.seam.desktop[theme] = await renderedSeam(true)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  for (const theme of themes) {
    await chooseTheme(theme)
    observations.seam.phone[theme] = await renderedSeam(true)
  }
  for (const theme of themes) {
    for (const breakpoint of ['desktop', 'phone']) {
      const observed = observations.seam[breakpoint][theme]
      assertEqual(observed.user_text, expectedSeam[theme].user, `${breakpoint} ${theme} user text seam`)
      if (!observed.composer.backgroundColor.includes(expectedSeam[theme].composerRgb)) {
        throw new Error(`${breakpoint} ${theme} composer escaped its glass token: ${observed.composer.backgroundColor}`)
      }
      if (!observed.composer.borderColor.includes(expectedSeam[theme].lineRgb)) {
        throw new Error(`${breakpoint} ${theme} composer border escaped its line token: ${observed.composer.borderColor}`)
      }
    }
  }

  await chooseTheme('gold-lines')
  await page.reload({ waitUntil: 'domcontentloaded' })
  console.log('M2UX4 step: persistence reload')
  await frame('header').getByTestId('connection').getByText('Palace ready').waitFor({ state: 'attached' })
  await page.getByTestId('rack-grid').waitFor()
  observations.persistence = {
    selected: await page.getByTestId('theme-control').inputValue(),
    root: await page.locator('html').getAttribute('data-theme'),
    chat_frame: await frameTheme('chat'),
  }
  assertEqual(observations.persistence.selected, 'gold-lines', 'persistent selected theme')
  assertEqual(observations.persistence.root, 'gold-lines', 'persistent host theme')
  assertEqual(observations.persistence.chat_frame, 'gold-lines', 'persistent iframe theme')

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  await writeFile(
    join(evidenceDir, 'themes-rendered.json'),
    `${JSON.stringify({
      fixture: 'M2UX4 REGRESSION',
      observations,
      console_problems: consoleProblems,
      page_errors: pageErrors,
    }, null, 2)}\n`,
    'utf8',
  )
  console.log('M2UX4 themes PASS: three faces, phone control, persistence, seam, and fixed rim')
} finally {
  await context.close()
  await browser.close()
}

async function waitForRack() {
  await frame('header').getByTestId('connection').getByText('Palace ready').waitFor()
  await page.getByTestId('rack-grid').waitFor()
  await frame('vitals').getByText('Disk free').waitFor()
}

async function sendSeamPrompt() {
  const chat = frame('chat')
  await chat.getByTestId('composer').fill('Theme seam check')
  await chat.getByTestId('send').click()
  await chat.locator('.message--user .message__content').getByText('Theme seam check').waitFor()
}

async function chooseTheme(theme, waitForUser = true) {
  await page.getByTestId('theme-control').selectOption(theme)
  await page.waitForFunction((wanted) => document.documentElement.dataset.theme === wanted, theme)
  await page.waitForFunction((wanted) => {
    const frames = [...document.querySelectorAll('iframe[data-testid^="rack-plugin-frame-"]')]
    return frames.length >= 5 && frames.every((element) => new URL(element.src).searchParams.get('theme') === wanted)
  }, theme)
  await frame('chat').locator(`html[data-theme="${theme}"]`).waitFor()
  if (waitForUser) {
    await frame('chat').locator('.message--user .message__content').getByText('Theme seam check').waitFor()
  }
}

async function renderedSeam(includeUser) {
  const userText = includeUser
    ? await frame('chat').locator('.message--user .message__content').evaluate(
        (element) => getComputedStyle(element).color,
      )
    : null
  const composer = await frame('chat').locator('.composer').evaluate((element) => {
    const style = getComputedStyle(element)
    return { backgroundColor: style.backgroundColor, borderColor: style.borderColor }
  })
  const frameState = {}
  for (const moduleId of ['header', 'threads', 'chat', 'memory', 'vitals', 'context_bars']) {
    frameState[moduleId] = await frameTheme(moduleId)
  }
  return {
    root: await page.locator('html').getAttribute('data-theme'),
    selected: await page.getByTestId('theme-control').inputValue(),
    user_text: userText,
    composer,
    frames: frameState,
    module_border: await page.getByTestId('rack-module-chat').evaluate((element) => getComputedStyle(element).borderColor),
  }
}

async function verifyPhoneControlLane() {
  const control = await page.getByTestId('theme-control').boundingBox()
  const header = await page.getByTestId('rack-plugin-frame-header').boundingBox()
  const chat = await page.getByTestId('rack-module-chat').boundingBox()
  if (control === null || header === null || chat === null) {
    throw new Error('phone control-lane geometry is unavailable')
  }
  const headerBottom = header.y + header.height
  const controlBottom = control.y + control.height
  if (control.y < headerBottom || controlBottom > chat.y) {
    throw new Error(`phone theme control escaped its reserved lane: ${JSON.stringify({ control, header, chat })}`)
  }
  return { control, header_bottom: headerBottom, chat_top: chat.y }
}

async function verifyReflectionSlide() {
  const module = page.getByTestId('rack-module-vitals')
  const before = await rimState(module)
  const source = module.locator('.rack-module__drag')
  const target = page.getByTestId('rack-module-context_bars').locator('.rack-module__drag')
  const sourceBox = await source.boundingBox()
  const targetBox = await target.boundingBox()
  if (sourceBox === null || targetBox === null) throw new Error('rim drag geometry unavailable')
  await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, { steps: 8 })
  await page.mouse.up()
  await page.waitForFunction((previousX) => {
    const element = document.querySelector('[data-testid="rack-module-vitals"]')
    return element !== null && element.getBoundingClientRect().x !== previousX
  }, before.x)
  await page.mouse.move(640, 0)
  await page.waitForTimeout(80)
  const after = await rimState(module)
  if (before.attachment !== 'fixed' || after.attachment !== 'fixed') {
    throw new Error(`chrome reflection is not viewport-fixed: ${JSON.stringify({ before, after })}`)
  }
  if (before.image !== after.image || before.x === after.x) {
    throw new Error(`rim did not move under one fixed reflection field: ${JSON.stringify({ before, after })}`)
  }
  return { before, after }
}

async function rimState(locator) {
  return locator.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const rim = getComputedStyle(element, '::after')
    return {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      attachment: rim.backgroundAttachment,
      image: rim.backgroundImage,
      padding: rim.paddingTop,
    }
  })
}

async function frameTheme(moduleId) {
  return frame(moduleId).locator('html').getAttribute('data-theme')
}

function frame(moduleId) {
  return page.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(`${label}: expected ${expected}, got ${actual}`)
}
