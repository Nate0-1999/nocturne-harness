import { useState, type FormEvent, type KeyboardEvent } from 'react'

import {
  canonicalProjectPath,
  projectPathEditValue,
  projectPathError,
  projectScopeLabel,
} from './projectPath'

export interface ProjectSelectorProps {
  selectedThreadId: string | null
  currentProjectKey: string | null
  projectPaths: readonly string[]
  awaitingSnapshot: boolean
  switching: boolean
  onSelect: (projectKey: string) => Promise<unknown>
}

export function ProjectSelector({
  selectedThreadId,
  currentProjectKey,
  projectPaths,
  awaitingSnapshot,
  switching,
  onSelect,
}: ProjectSelectorProps) {
  const [projectEdit, setProjectEdit] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const projectDraft = projectEdit ?? projectPathEditValue(currentProjectKey)
  const scopeLabel = projectScopeLabel(currentProjectKey)
  const status = switching
    ? 'Switching…'
    : feedback ?? (awaitingSnapshot ? 'Loading…' : '')

  function openProject() {
    if (projectEdit === null && currentProjectKey === null) {
      setFeedback('This thread is unscoped. Enter a project path to open a scoped thread.')
      return
    }
    const validation = projectPathError(projectDraft)
    if (validation !== null) {
      setFeedback(validation)
      return
    }
    const projectKey = canonicalProjectPath(projectDraft)
    setProjectEdit(projectKey)
    if (projectKey === currentProjectKey && !awaitingSnapshot) {
      setProjectEdit(null)
      setFeedback(null)
      return
    }
    setFeedback(null)
    void onSelect(projectKey).catch(() => {
      setProjectEdit(null)
      setFeedback('Couldn’t switch projects. Try again.')
    })
  }

  function submitProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    openProject()
  }

  function handleProjectKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter' || event.nativeEvent.isComposing) {
      return
    }
    event.preventDefault()
    openProject()
  }

  return (
    <form className="project-selector" aria-label="Current project" onSubmit={submitProject}>
      <label htmlFor="current-project-path">
        <span>Project</span>
        <input
          id="current-project-path"
          data-testid="current-project"
          type="text"
          list="known-project-paths"
          value={projectDraft}
          placeholder={currentProjectKey === null ? 'Enter project path' : 'Choose a project'}
          disabled={awaitingSnapshot || selectedThreadId === null}
          aria-invalid={feedback !== null}
          aria-describedby="project-selector-status"
          title={currentProjectKey ?? 'Unscoped thread'}
          onChange={(event) => {
            setProjectEdit(event.currentTarget.value)
            setFeedback(null)
          }}
          onKeyDown={handleProjectKeyDown}
        />
      </label>
      <datalist id="known-project-paths">
        {projectPaths.map((path) => <option value={path} key={path} />)}
      </datalist>
      <button className="visually-hidden" type="submit">Open project</button>
      <span
        id="project-selector-status"
        className="project-selector__status"
        data-error={feedback !== null || undefined}
        aria-live="polite"
      >
        {scopeLabel !== null && <span className="project-selector__scope">{scopeLabel}</span>}
        {scopeLabel !== null && status !== '' && ' · '}
        {status}
      </span>
    </form>
  )
}
