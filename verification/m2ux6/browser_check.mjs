/** PLAN M2UX6 / B.6 r7,r12 / D.2 115-120: rendered grimoire motion and persistence. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const baseUrl = process.argv.includes('--base-url')
  ? process.argv[process.argv.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8809'
const fixtureUrl = `${baseUrl}/?fixture=${encodeURIComponent('M2UX6 REGRESSION')}`
const themes = ['wizard-mode', 'technomancer']
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
const observations = { fixture: 'M2UX6 REGRESSION', themes: {}, persistence: null }
const consoleProblems = []
const pageErrors = []

page.on('console', (message) => {
  if (message.type() === 'error') consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))

try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(fixtureUrl, { waitUntil: 'domcontentloaded' })
  await waitForRack(page)

  for (const [index, theme] of themes.entries()) {
    await chooseTheme(page, theme)
    const mount = await motifState(page, theme)
    assertFinite(mount.hostHead, `${theme} module mount`)
    assertFinite(mount.topbar, `${theme} topbar mount`)
    await page.screenshot({ path: join(evidenceDir, `0${index * 4 + 1}-${theme}-mount.png`) })

    await page.getByTestId('rack-module-chat').locator('.rack-module__chrome').hover({ force: true })
    await page.waitForTimeout(120)
    const hover = await motifState(page, theme)
    if (!(await page.getByTestId('rack-module-chat').evaluate((element) => element.matches(':hover')))) {
      throw new Error(`${theme} hover did not reach the real Rack module`)
    }
    if (theme === 'wizard-mode') assertFinite(hover.hostMargin, `${theme} module hover`)
    await page.screenshot({ path: join(evidenceDir, `0${index * 4 + 2}-${theme}-hover.png`) })

    await page.mouse.move(1260, 70)
    await page.waitForTimeout(900)
    const empty = await motifState(page, theme)
    assertInfinite(empty.emptyAfter, `${theme} empty-state axis one`)
    assertInfinite(empty.emptyBefore, `${theme} empty-state axis two`)
    if (theme === 'technomancer') assertInfinite(empty.ambient, `${theme} background scanline`)
    await page.screenshot({ path: join(evidenceDir, `0${index * 4 + 3}-${theme}-empty.png`) })

    const reduced = await reducedState(browser, theme)
    for (const [surface, state] of Object.entries(reduced)) {
      if (state.animationName !== 'none') {
        throw new Error(`${theme} reduced motion left ${surface} animated: ${JSON.stringify(state)}`)
      }
    }
    observations.themes[theme] = { mount, hover, empty, reduced }
  }

  await chooseTheme(page, 'technomancer')
  await page.reload({ waitUntil: 'domcontentloaded' })
  await waitForRack(page)
  await openSettings(page)
  observations.persistence = {
    selected: await page.getByTestId('theme-control').inputValue(),
    host: await page.locator('html').getAttribute('data-theme'),
    chat: await frame(page, 'chat').locator('html').getAttribute('data-theme'),
  }
  for (const [surface, value] of Object.entries(observations.persistence)) {
    if (value !== 'technomancer') throw new Error(`theme persistence failed at ${surface}: ${value}`)
  }

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  await writeFile(
    join(evidenceDir, 'grimoire-rendered.json'),
    `${JSON.stringify({ ...observations, console_problems: consoleProblems, page_errors: pageErrors }, null, 2)}\n`,
    'utf8',
  )
  console.log('M2UX6 themes PASS: mount, hover, empty ambience, reduced motion, and persistence')
} finally {
  await context.close()
  await browser.close()
}

async function reducedState(browserInstance, theme) {
  const reducedContext = await browserInstance.newContext({
    viewport: { width: 1280, height: 900 },
    reducedMotion: 'reduce',
  })
  const reducedPage = await reducedContext.newPage()
  try {
    await reducedPage.goto(fixtureUrl, { waitUntil: 'domcontentloaded' })
    await waitForRack(reducedPage)
    await chooseTheme(reducedPage, theme)
    await reducedPage.screenshot({
      path: join(evidenceDir, `${theme === 'wizard-mode' ? '04' : '08'}-${theme}-reduced.png`),
    })
    const state = await motifState(reducedPage, theme)
    return {
      hostHead: state.hostHead,
      hostMargin: state.hostMargin,
      hostBottom: state.hostBottom,
      topbar: state.topbar,
      emptyAfter: state.emptyAfter,
      emptyBefore: state.emptyBefore,
      ambient: state.ambient,
    }
  } finally {
    await reducedContext.close()
  }
}

async function motifState(targetPage, theme) {
  const hostHead = await pseudo(targetPage.getByTestId('rack-module-chat').locator('.rack-module__chrome'), '::before')
  const hostContent = targetPage.getByTestId('rack-module-chat').locator('.rack-module__content')
  const chat = frame(targetPage, 'chat')
  return {
    theme,
    hostHead,
    hostMargin: await pseudo(hostContent, '::after'),
    hostBottom: await pseudo(hostContent, '::before'),
    topbar: await pseudo(frame(targetPage, 'header').locator('.topbar'), '::after'),
    emptyAfter: await pseudo(chat.locator('.transcript__inner'), '::after'),
    emptyBefore: await pseudo(chat.locator('.transcript__inner'), '::before'),
    ambient: await pseudo(targetPage.locator('.rack-ambient'), '::after'),
    messageContentAnimation: await chat.locator('.thread-empty').evaluate(
      (element) => getComputedStyle(element).animationName,
    ),
  }
}

async function pseudo(locator, pseudoElement) {
  return locator.evaluate((element, pseudoName) => {
    const style = getComputedStyle(element, pseudoName)
    return {
      animationName: style.animationName,
      animationIterationCount: style.animationIterationCount,
      hasGeneratedStrip: style.backgroundImage.startsWith('url("data:image/svg+xml'),
    }
  }, pseudoElement)
}

async function chooseTheme(targetPage, theme) {
  await openSettings(targetPage)
  await targetPage.getByTestId('theme-control').selectOption(theme)
  await targetPage.waitForFunction((wanted) => document.documentElement.dataset.theme === wanted, theme)
  await targetPage.waitForFunction((wanted) => {
    const frames = [...document.querySelectorAll('iframe[data-testid^="rack-plugin-frame-"]')]
    return frames.length >= 5 && frames.every((element) => new URL(element.src).searchParams.get('theme') === wanted)
  }, theme)
  await frame(targetPage, 'chat').locator(`html[data-theme="${theme}"]`).waitFor()
  await targetPage.getByRole('button', { name: 'Close app settings' }).click()
}

async function openSettings(targetPage) {
  if ((await targetPage.getByTestId('theme-control').count()) === 0) {
    await targetPage.getByTestId('app-settings-toggle').click()
  }
  await targetPage.getByTestId('theme-control').waitFor()
}

async function waitForRack(targetPage) {
  await frame(targetPage, 'header').getByTestId('connection').getByText('Palace ready').waitFor()
  await targetPage.getByTestId('rack-module-chat').waitFor()
  await frame(targetPage, 'chat').getByTestId('composer').waitFor()
  if ((await frame(targetPage, 'chat').getByTestId('thread-empty').count()) === 0) {
    await frame(targetPage, 'threads').getByTestId('new-thread').click({ force: true })
  }
  await frame(targetPage, 'chat').getByTestId('thread-empty').waitFor()
}

function frame(targetPage, moduleId) {
  return targetPage.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}

function assertFinite(state, label) {
  if (state.animationName === 'none' || state.animationIterationCount === 'infinite') {
    throw new Error(`${label} is not a finite conjuration: ${JSON.stringify(state)}`)
  }
}

function assertInfinite(state, label) {
  if (state.animationName === 'none' || state.animationIterationCount !== 'infinite') {
    throw new Error(`${label} is not reserved ambience: ${JSON.stringify(state)}`)
  }
}
