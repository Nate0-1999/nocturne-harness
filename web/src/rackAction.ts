export async function runRackAction<T>(
  action: () => T | Promise<T>,
  reportFailure: (message: string) => void,
): Promise<T> {
  try {
    return await action()
  } catch (error) {
    reportFailure(error instanceof Error ? error.message : 'Rack action failed')
    throw error
  }
}
