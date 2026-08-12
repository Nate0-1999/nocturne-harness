const DECIMAL = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/

const moneyToCents = new Intl.NumberFormat(undefined, {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const subCentMoney = new Intl.NumberFormat(undefined, {
  style: 'currency',
  currency: 'USD',
  maximumSignificantDigits: 3,
})

const percent = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

const quantity = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 1,
})

const compactQuantity = new Intl.NumberFormat(undefined, {
  notation: 'compact',
  maximumFractionDigits: 1,
})

/** PLAN M2ST3 HUMAN NUMBERS is presentation-only; source decimals remain untouched. */
export function formatHumanUsd(value: string): string {
  const numeric = decimal(value, 'Money')
  return Math.abs(numeric) > 0 && Math.abs(numeric) < 0.01
    ? subCentMoney.format(numeric)
    : moneyToCents.format(numeric)
}

/** PLAN M2ST3 renders percentages at one decimal without changing their ledger value. */
export function formatHumanPercent(value: string | number): string {
  return `${percent.format(finite(value, 'Percentage'))}%`
}

/** PLAN M2ST3 keeps measured rates readable while preserving raw values upstream. */
export function formatHumanQuantity(value: string | number): string {
  return quantity.format(finite(value, 'Quantity'))
}

/** SPEC P2.2 keeps token scale glanceable in Context Bars. */
export function formatHumanCount(value: number): string {
  return compactQuantity.format(finite(value, 'Count'))
}

function decimal(value: string, name: string): number {
  if (!DECIMAL.test(value)) {
    throw new TypeError(`${name} must be an exact decimal string`)
  }
  return finite(value, name)
}

function finite(value: string | number, name: string): number {
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) {
    throw new TypeError(`${name} must be finite`)
  }
  return numeric
}
