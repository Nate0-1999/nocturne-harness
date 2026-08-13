export interface ProviderErrorPayload {
  classification: 'context_length' | 'provider_refusal'
  message: string
  model: string
  status_code?: number
  code?: string
  provider_code?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseProviderError(value: unknown): ProviderErrorPayload | null {
  if (!isRecord(value)) {
    return null
  }
  const statusCode = value.status_code
  const code = value.code
  const providerCode = value.provider_code
  if (
    !['context_length', 'provider_refusal'].includes(String(value.classification)) ||
    typeof value.message !== 'string' || value.message.trim() === '' ||
    typeof value.model !== 'string' || value.model.trim() === '' ||
    (statusCode != null &&
      (typeof statusCode !== 'number' || !Number.isInteger(statusCode) ||
        statusCode < 100 || statusCode > 599)) ||
    (code != null && (typeof code !== 'string' || code.trim() === '')) ||
    (providerCode != null &&
      (typeof providerCode !== 'string' || providerCode.trim() === ''))
  ) {
    return null
  }
  return {
    classification: value.classification as ProviderErrorPayload['classification'],
    message: value.message,
    model: value.model,
    ...(statusCode == null ? {} : { status_code: statusCode }),
    ...(code == null ? {} : { code }),
    ...(providerCode == null ? {} : { provider_code: providerCode }),
  }
}
