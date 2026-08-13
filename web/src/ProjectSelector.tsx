import { useState, type FormEvent, type KeyboardEvent } from 'react'

import {
  canonicalProjectPath,
  initialProjectControlState,
  projectPathEditValue,
  projectPathError,
  reconcileProjectControlState,
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
  const [storedControl, setStoredControl] = useState(() =>
    initialProjectControlState(selectedThreadId, currentProjectKey))
  const control = reconcileProjectControlState(
    storedControl,
    selectedThreadId,
    currentProjectKey,
    awaitingSnapshot,
  )
  if (control !== storedControl) {
    setStoredControl(control)
  }
  const projectDraft = control.edit ?? projectPathEditValue(currentProjectKey)
  const scopeLabel = awaitingSnapshot ? null : projectScopeLabel(currentProjectKey)
  const status = switching
    ? 'Switching…'
    : control.feedback ?? (awaitingSnapshot ? 'Loading…' : '')

  function openProject() {
    if (control.edit === null && currentProjectKey === null) {
      setStoredControl({
        ...control,
        feedback: 'This thread is unscoped. Enter a project path to open a scoped thread.',
      })
      return
    }
    const validation = projectPathError(projectDraft)
    if (validation !== null) {
      setStoredControl({ ...control, feedback: validation })
      return
    }
    const projectKey = canonicalProjectPath(projectDraft)
    if (projectKey === currentProjectKey && !awaitingSnapshot) {
      setStoredControl(initialProjectControlState(selectedThreadId, currentProjectKey))
      return
    }
    const submittedControl = {
      ...control,
      edit: projectKey,
      feedback: null,
      submitted: true,
    }
    setStoredControl(submittedControl)
    void onSelect(projectKey).catch(() => {
      setStoredControl((latest) => latest.contextKey === submittedControl.contextKey
        ? {
            ...latest,
            edit: null,
            feedback: 'Couldn’t switch projects. Try again.',
            submitted: false,
          }
        : latest)
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
          aria-invalid={control.feedback !== null}
          aria-describedby="project-selector-status"
          title={awaitingSnapshot
            ? 'Waiting for daemon project'
            : currentProjectKey ?? 'Unscoped thread'}
          onChange={(event) => {
            setStoredControl({
              ...control,
              edit: event.currentTarget.value,
              feedback: null,
              submitted: false,
            })
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
        data-error={control.feedback !== null || undefined}
        aria-live="polite"
      >
        {scopeLabel !== null && <span className="project-selector__scope">{scopeLabel}</span>}
        {scopeLabel !== null && status !== '' && ' · '}
        {status}
      </span>
    </form>
  )
}
