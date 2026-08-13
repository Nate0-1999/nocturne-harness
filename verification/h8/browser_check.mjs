/**
 * Drive the production H8 SPA like a user and assert rendered outcomes.
 *
 * The fixture process owns the deterministic model and exact-ID cleanup
 * boundary. This script owns B.6 rule 7: browser clicks, sequential typing,
 * rendered DOM assertions, responsive layout assertions, and screenshots.
 */

import { createRequire } from 'node:module'
import { copyFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(
  new URL('../../web/package.json', import.meta.url),
)
const { chromium } = requireFromWeb('playwright-core')

const evidenceDir = dirname(fileURLToPath(import.meta.url))
const options = parseOptions(process.argv.slice(2))
const viewport =
  options.mode === 'mobile'
    ? { width: 390, height: 844 }
    : { width: 1440, height: 900 }
const stem = `scripted-${options.mode}`
const rememberScreenshot = join(
  evidenceDir,
  `${stem}-01-remember-${viewport.width}x${viewport.height}.png`,
)
const markdownScreenshot = join(
  evidenceDir,
  `${stem}-02-markdown-${viewport.width}x${viewport.height}.png`,
)
const renderedPath = join(evidenceDir, `rendered-${stem}.json`)
const cleanupPath = join(evidenceDir, `cleanup-result-${stem}.json`)
const tracePath = join(evidenceDir, 'trace.jsonl')
const preservedTracePath = join(evidenceDir, `trace-${stem}.jsonl`)

let browser
let cleanupResult = null

try {
  const expectation = await fetchJson(`${options.baseUrl}/__scenario__/expectation`)
  browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
  })
  const context = await browser.newContext({
    viewport,
    screen: viewport,
    deviceScaleFactor: 1,
  })
  const page = await context.newPage()
  const consoleProblems = []
  const pageErrors = []

  page.on('console', (message) => {
    if (message.type() === 'warning' || message.type() === 'error') {
      consoleProblems.push({
        type: message.type(),
        text: message.text(),
      })
    }
  })
  page.on('pageerror', (error) => {
    pageErrors.push(error.message)
  })

  await page.goto(options.baseUrl, { waitUntil: 'domcontentloaded' })
  await page.getByTestId('connection').getByText('Palace ready').waitFor()
  await waitForModel(page, expectation.resolved_model)

  await typeAndSend(page, expectation.remember_command)
  await page
    .getByText(`Remembered '${expectation.remember_label}'`, { exact: false })
    .waitFor({ state: 'visible' })
  await page.screenshot({ path: rememberScreenshot })

  if (options.mode === 'mobile') {
    await page.getByTestId('mobile-threads').click()
  }
  await page.getByTestId('new-thread').click()
  await page.getByTestId('thread-empty').waitFor({ state: 'visible' })
  await waitForModel(page, expectation.resolved_model)

  await typeAndSend(page, expectation.markdown_prompt)
  await page.getByTestId('memory-gate').waitFor({ state: 'visible' })
  await waitForModel(page, expectation.resolved_model)
  if ((await page.getByTestId('assistant-markdown').count()) !== 0) {
    throw new Error('the model rendered content before the memory gate continued')
  }
  await page.getByTestId('memory-gate-continue').click()
  await page.getByTestId('memory-gate').waitFor({ state: 'detached' })
  await page
    .locator('[data-role="assistant"] h2', { hasText: 'H8 Markdown proof' })
    .waitFor({ state: 'visible' })
  await page
    .locator('[data-role="assistant"] pre code', { hasText: 'print("h8")' })
    .waitFor({ state: 'visible' })

  const transcript = page.getByTestId('transcript')
  await transcript.evaluate((element) => {
    element.scrollTop = element.scrollHeight
  })
  await page.screenshot({ path: markdownScreenshot })

  const rendered = await collectRenderedEvidence(page, expectation.resolved_model)
  rendered.consoleProblems = consoleProblems
  rendered.pageErrors = pageErrors
  rendered.mode = options.mode
  rendered.baseUrl = options.baseUrl
  rendered.screenshots = {
    remember: rememberScreenshot,
    markdown: markdownScreenshot,
  }
  assertRendered(rendered, options.mode)
  await writeFile(renderedPath, `${JSON.stringify(rendered, null, 2)}\n`, 'utf8')
  console.log(`H8 rendered ${options.mode} PASS: ${renderedPath}`)
} finally {
  if (browser !== undefined) {
    await browser.close()
  }
  cleanupResult = await cleanupExactFixture(options.baseUrl)
  await writeFile(cleanupPath, `${JSON.stringify(cleanupResult, null, 2)}\n`, 'utf8')
  await copyFile(tracePath, preservedTracePath)
  console.log(`H8 exact cleanup: ${cleanupPath}`)
  console.log(`H8 preserved trace: ${preservedTracePath}`)
}

function parseOptions(args) {
  const values = new Map()
  for (let index = 0; index < args.length; index += 2) {
    values.set(args[index], args[index + 1])
  }
  const baseUrl = values.get('--base-url')
  const mode = values.get('--mode')
  if (
    typeof baseUrl !== 'string' ||
    !/^http:\/\/127\.0\.0\.1:\d+$/.test(baseUrl)
  ) {
    throw new Error('--base-url must be an http://127.0.0.1:<port> origin')
  }
  if (mode !== 'desktop' && mode !== 'mobile') {
    throw new Error('--mode must be desktop or mobile')
  }
  return { baseUrl, mode }
}

async function fetchJson(url, init) {
  const response = await fetch(url, init)
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(`${response.status} from ${url}: ${JSON.stringify(payload)}`)
  }
  return payload
}

async function cleanupExactFixture(baseUrl) {
  const health = await fetchJson(`${baseUrl}/__scenario__/health`)
  if (health.created_memory_id === null) {
    return {
      ok: true,
      tombstoned: [],
      remaining_active_ids: [],
      note: 'fixture created no memory',
    }
  }
  return fetchJson(`${baseUrl}/__scenario__/cleanup`, { method: 'POST' })
}

async function waitForModel(page, expectedModel) {
  const model = page.getByTestId('active-model')
  await model.waitFor({ state: 'visible' })
  await page.waitForFunction(
    ({ selector, expected }) => {
      const value = document.querySelector(selector)
      return value?.textContent?.trim() === expected
    },
    {
      selector: '[data-testid="active-model"] .chat-header__model-value',
      expected: expectedModel,
    },
  )
}

async function typeAndSend(page, prompt) {
  const composer = page.getByTestId('composer')
  await composer.click()
  await composer.pressSequentially(prompt, { delay: 1 })
  await page.getByTestId('send').click()
}

async function collectRenderedEvidence(page, expectedModel) {
  return page.evaluate((expected) => {
    const assistant =
      Array.from(document.querySelectorAll('[data-role="assistant"]')).at(-1) ?? null
    const user =
      Array.from(document.querySelectorAll('[data-role="user"]')).at(-1) ?? null
    const model = document.querySelector(
      '[data-testid="active-model"] .chat-header__model-value',
    )
    const code = assistant?.querySelector('pre code') ?? null
    const table = assistant?.querySelector('table') ?? null
    const pre = assistant?.querySelector('pre') ?? null
    const modelRect = model?.getBoundingClientRect() ?? null
    const viewport = {
      width: document.documentElement.clientWidth,
      height: document.documentElement.clientHeight,
    }

    const visibleActions = Array.from(
      document.querySelectorAll('button, textarea, a[href], [role="button"]'),
    )
      .filter((element) => {
        if (!(element instanceof HTMLElement) || element.closest('[inert]')) {
          return false
        }
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return (
          style.display !== 'none' &&
          style.visibility !== 'hidden' &&
          rect.width > 0 &&
          rect.height > 0 &&
          rect.right > 0 &&
          rect.bottom > 0 &&
          rect.left < viewport.width &&
          rect.top < viewport.height
        )
      })
      .map((element) => {
        const rect = element.getBoundingClientRect()
        return {
          label:
            element.getAttribute('aria-label') ??
            element.textContent?.trim() ??
            element.tagName.toLowerCase(),
          width: rect.width,
          height: rect.height,
        }
      })

    const scrollSurface = (element) => {
      if (!(element instanceof HTMLElement)) {
        return null
      }
      const style = getComputedStyle(element)
      return {
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        overflowX: style.overflowX,
        reachable:
          element.scrollWidth <= element.clientWidth ||
          style.overflowX === 'auto' ||
          style.overflowX === 'scroll',
      }
    }

    return {
      expectedModel: expected,
      viewport,
      documentWidth: {
        client: document.documentElement.clientWidth,
        scroll: document.documentElement.scrollWidth,
      },
      model: {
        text: model?.textContent?.trim() ?? null,
        fullyVisible:
          modelRect !== null &&
          modelRect.left >= 0 &&
          modelRect.right <= viewport.width &&
          modelRect.top >= 0 &&
          modelRect.bottom <= viewport.height &&
          model.scrollWidth <= model.clientWidth,
      },
      assistantCounts: {
        h2: assistant?.querySelectorAll('h2').length ?? 0,
        strong: assistant?.querySelectorAll('strong').length ?? 0,
        em: assistant?.querySelectorAll('em').length ?? 0,
        listItems: assistant?.querySelectorAll('ul > li').length ?? 0,
        table: assistant?.querySelectorAll('table').length ?? 0,
        preCode: assistant?.querySelectorAll('pre > code').length ?? 0,
      },
      assistantText: assistant?.textContent ?? null,
      rawHtml: {
        buttonElements: assistant?.querySelectorAll('[data-h8-raw="true"]').length ?? 0,
        scriptElements: assistant?.querySelectorAll('script').length ?? 0,
        buttonLiteral:
          assistant?.textContent?.includes(
            '<button data-h8-raw="true">Unsafe button</button>',
          ) ?? false,
        scriptLiteral:
          assistant?.textContent?.includes(
            '<script>globalThis.__h8RawHtmlExecuted = true</script>',
          ) ?? false,
        executedType: typeof globalThis.__h8RawHtmlExecuted,
      },
      codeFontFamily: code === null ? null : getComputedStyle(code).fontFamily,
      user: {
        text: user?.textContent ?? null,
        plainMarkers:
          user?.textContent?.includes('**plain-user-text**') === true &&
          user?.textContent?.includes(
            '<button data-h8-user-raw="true">unsafe</button>',
          ) === true,
        richDescendants:
          user?.querySelectorAll(
            'h1,h2,h3,h4,h5,h6,strong,em,ul,ol,table,pre,code,button,script',
          ).length ?? 0,
      },
      table: scrollSurface(table),
      codeBlock: scrollSurface(pre),
      visibleActions,
      appError: document.querySelector('[data-testid="error-line"]')?.textContent ?? null,
    }
  }, expectedModel)
}

function assertRendered(result, mode) {
  const failures = []
  const count = result.assistantCounts
  if (
    count.h2 !== 1 ||
    count.strong !== 1 ||
    count.em !== 1 ||
    count.listItems !== 2 ||
    count.table !== 1 ||
    count.preCode !== 1
  ) {
    failures.push(`Markdown structure differs: ${JSON.stringify(count)}`)
  }
  if (
    !result.rawHtml.buttonLiteral ||
    !result.rawHtml.scriptLiteral ||
    result.rawHtml.buttonElements !== 0 ||
    result.rawHtml.scriptElements !== 0 ||
    result.rawHtml.executedType !== 'undefined'
  ) {
    failures.push(`raw HTML was not inert literal text: ${JSON.stringify(result.rawHtml)}`)
  }
  if (!result.user.plainMarkers || result.user.richDescendants !== 0) {
    failures.push(`user content was not plain text: ${JSON.stringify(result.user)}`)
  }
  if (
    result.model.text !== result.expectedModel ||
    !result.model.fullyVisible
  ) {
    failures.push(`resolved model was not fully visible: ${JSON.stringify(result.model)}`)
  }
  if (
    typeof result.codeFontFamily !== 'string' ||
    !/(mono|courier|consolas)/i.test(result.codeFontFamily)
  ) {
    failures.push(`code did not use a monospace face: ${result.codeFontFamily}`)
  }
  if (!result.table?.reachable || !result.codeBlock?.reachable) {
    failures.push('table or code block could not be reached horizontally')
  }
  if (result.consoleProblems.length > 0 || result.pageErrors.length > 0) {
    failures.push(
      `browser console was not clean: ${JSON.stringify({
        console: result.consoleProblems,
        page: result.pageErrors,
      })}`,
    )
  }
  if (result.appError !== null) {
    failures.push(`the app surfaced an error: ${result.appError}`)
  }
  if (mode === 'mobile') {
    if (
      result.viewport.width !== 390 ||
      result.viewport.height !== 844 ||
      result.documentWidth.client !== 390 ||
      result.documentWidth.scroll !== 390
    ) {
      failures.push(
        `390x844 layout overflowed: ${JSON.stringify({
          viewport: result.viewport,
          documentWidth: result.documentWidth,
        })}`,
      )
    }
    const undersized = result.visibleActions.filter(
      (action) => action.width < 44 || action.height < 44,
    )
    if (undersized.length > 0) {
      failures.push(`mobile actions smaller than 44px: ${JSON.stringify(undersized)}`)
    }
  }
  if (failures.length > 0) {
    throw new Error(failures.join('\n'))
  }
}
