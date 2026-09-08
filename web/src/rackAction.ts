export async function runRackAction<T>(
  action: () => T | Promise<T>,
  reportFailure: (message: string) => void,
  reportRecovery: () => void = () => {},
): Promise<T> {
  try {
    const result = await action()
    reportRecovery()
    return result
  } catch (error) {
    reportFailure(error instanceof Error ? error.message : 'Rack action failed')
    throw error
  }
}
