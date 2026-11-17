import { failureMessage } from './requestFailure.ts'

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
    reportFailure(failureMessage(error, 'The action could not finish. Try again.'))
    throw error
  }
}
