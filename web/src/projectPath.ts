export const DEFAULT_PROJECT_PATH = 'build-test'
export const MAX_PROJECT_PATH_CODE_POINTS = 256
export const UNSCOPED_PROJECT_LABEL = 'Unscoped'

export function projectPathEditValue(projectKey: string | null): string {
  return projectKey ?? ''
}

export function projectScopeLabel(projectKey: string | null): string | null {
  return projectKey === null ? UNSCOPED_PROJECT_LABEL : null
}

export function projectSelectorContextKey(
  selectedThreadId: string | null,
  currentProjectKey: string | null,
): string {
  return JSON.stringify([selectedThreadId, currentProjectKey])
}

export interface ProjectControlState {
  contextKey: string
  edit: string | null
  feedback: string | null
  submitted: boolean
}

export function initialProjectControlState(
  selectedThreadId: string | null,
  currentProjectKey: string | null,
): ProjectControlState {
  return {
    contextKey: projectSelectorContextKey(selectedThreadId, currentProjectKey),
    edit: null,
    feedback: null,
    submitted: false,
  }
}

export function reconcileProjectControlState(
  state: ProjectControlState,
  selectedThreadId: string | null,
  currentProjectKey: string | null,
  awaitingSnapshot: boolean,
): ProjectControlState {
  const contextKey = projectSelectorContextKey(selectedThreadId, currentProjectKey)
  if (state.contextKey !== contextKey || (state.submitted && !awaitingSnapshot)) {
    return initialProjectControlState(selectedThreadId, currentProjectKey)
  }
  return state
}

type ProjectCatalogEntry = {
  project_key: string | null
  thread_id: string
  updated_at: string
}

export function canonicalProjectPath(value: string): string {
  const path = value.trim()
  if (path.length === 0) {
    throw new TypeError('Enter a project path.')
  }
  if (Array.from(path).length > MAX_PROJECT_PATH_CODE_POINTS) {
    throw new TypeError('Project paths must be 256 characters or fewer.')
  }
  if (path.startsWith('/')) {
    throw new TypeError('Project paths must be relative.')
  }
  if (path.includes('\\')) {
    throw new TypeError('Use forward slashes in project paths.')
  }
  const segments = path.split('/')
  if (segments.some((segment) => segment.length === 0)) {
    throw new TypeError('Project paths cannot contain empty sections.')
  }
  if (segments.some((segment) => segment === '.' || segment === '..')) {
    throw new TypeError('Project paths cannot contain . or .. sections.')
  }
  return path
}

export function projectPathError(value: string): string | null {
  try {
    canonicalProjectPath(value)
    return null
  } catch (error) {
    return error instanceof Error ? error.message : 'Enter a valid project path.'
  }
}

export function isCanonicalProjectPath(value: unknown): value is string {
  if (typeof value !== 'string') return false
  try {
    return canonicalProjectPath(value) === value
  } catch {
    return false
  }
}

export function knownProjectPaths(entries: readonly ProjectCatalogEntry[]): string[] {
  const paths = new Set<string>([DEFAULT_PROJECT_PATH])
  for (const entry of entries) {
    if (entry.project_key !== null) {
      paths.add(entry.project_key)
    }
  }
  return [...paths].sort((left, right) => left.localeCompare(right))
}

export function newestProjectThread(
  entries: readonly ProjectCatalogEntry[],
  projectPath: string,
): ProjectCatalogEntry | null {
  const canonical = canonicalProjectPath(projectPath)
  return entries
    .filter((entry) => entry.project_key === canonical)
    .sort((left, right) => (
      right.updated_at.localeCompare(left.updated_at) ||
      right.thread_id.localeCompare(left.thread_id)
    ))[0] ?? null
}
