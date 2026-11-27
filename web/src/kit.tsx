/** PLAN M3UI: the one control kit. Every control in the app is one of these; the kit lint keeps it so.
 * Each part is the native element plus the kit class: props, handlers, aria and test ids pass straight
 * through, so swapping a raw control for its kit part changes its look and nothing else.
 * The module frame header is RackModuleFrame and the hover tip is ControlTooltip; both were already one. */
import { useState } from 'react'
import type {
  ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, Ref,
  SelectHTMLAttributes, TextareaHTMLAttributes,
} from 'react'
import {
  Archive, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Ban, Brain, ChartNoAxesColumn, Check, ChevronDown, ChevronUp,
  ChevronsUpDown, CircleDollarSign, CircleStop, Eye, FolderOpen, GripVertical, Inbox, Landmark, LayoutDashboard,
  Library, Maximize, MessageSquare, Mic, Minimize, Paperclip,
  Pause, Pencil, Pin, Play, Plus, RotateCcw, Rows3, Save, Search, Send, Settings,
  Square, SquareCheck, Trash2, Undo2, Upload, Volume2, X, ZoomIn, ZoomOut,
} from 'lucide-react'

/** SD-069 / FL-199: one meaning-to-icon table, using the unmodified Lucide set.
 * SD-096 (c): one icon per meaning and one meaning per icon. X takes a thing off the surface and
 * destroys nothing (a row removed, a panel closed); the bin destroys; the check approves or allows;
 * the barred circle denies; the folder is a folder or file, the speech square a conversation;
 * the empty and checked squares are only ever a switch's off and on, so stop is the ringed square.
 * Yes, No, Cancel and Reset carry no icon.
 * SD-129: the last row is the emblems the owner saw drawn and kept (report 346): the two views and
 * the Library on the toolbar, and five modules on the Off-screen bar. */
const ACTION_ICONS = {
  send: Send, stop: CircleStop, add: Plus, remove: X, delete: Trash2, refresh: RotateCcw,
  open: FolderOpen, thread: MessageSquare, settings: Settings, run: Play, pause: Pause, search: Search,
  close: X, expand: ChevronDown, collapse: ChevronUp, fit: Maximize, minimize: Minimize,
  save: Save, restore: Undo2, back: ArrowLeft, next: ArrowRight, up: ArrowUp,
  latest: ArrowDown, edit: Pencil, pin: Pin, unpin: Pin, archive: Archive,
  attach: Paperclip, import: Upload, preview: Eye, listen: Mic, speak: Volume2,
  approve: Check, deny: Ban, move: GripVertical, zoomIn: ZoomIn, zoomOut: ZoomOut,
  stage: LayoutDashboard, sheet: Rows3, library: Library, memory: Brain, spend: CircleDollarSign,
  contextBars: ChartNoAxesColumn, palaceState: Landmark, ingest: Inbox,
} as const

export type ButtonAction = keyof typeof ACTION_ICONS

/** SD-096 (b): one word per action in every module. A Button with an action and no words of its own
 * says this word; a longer label starts with it ("Save layout"). The owner's words stand beside the
 * table and are never renamed: Queue, Interject, Force retrain, Force values, Rewind, Pin, Audition,
 * Pop off, Deny, and the gate's Continue, Wrong and Never (SPEC C.6). */
const ACTION_WORDS: Record<ButtonAction, string> = {
  send: 'Send', stop: 'Stop', add: 'Add', remove: 'Remove', delete: 'Delete', refresh: 'Refresh',
  open: 'Open', thread: 'Open thread', settings: 'Settings', run: 'Run', pause: 'Pause', search: 'Search',
  close: 'Close', expand: 'Expand', collapse: 'Collapse', fit: 'Fit', minimize: 'Minimize',
  save: 'Save', restore: 'Restore', back: 'Back', next: 'Next', up: 'Up',
  latest: 'Latest', edit: 'Edit', pin: 'Pin', unpin: 'Unpin', archive: 'Archive',
  attach: 'Attach', import: 'Import', preview: 'Preview', listen: 'Listen', speak: 'Read aloud',
  approve: 'Approve', deny: 'Deny', move: 'Move', zoomIn: 'Zoom in', zoomOut: 'Zoom out',
  stage: 'Stage', sheet: 'Sheet', library: 'Library', memory: 'Memory Palace', spend: 'Spend',
  contextBars: 'Context Bars', palaceState: 'Palace State', ingest: 'Memory Ingest',
}

export function ActionIcon({ action }: { action: ButtonAction }) {
  const Icon = ACTION_ICONS[action]
  return <Icon className="kit-icon" aria-hidden="true" focusable="false" />
}

function join(...names: (string | false | undefined)[]): string {
  return names.filter(Boolean).join(' ')
}

export type ButtonVariant = 'primary' | 'quiet' | 'danger' | 'bare'

/** `bare` is a button that wears its content's look (a row, a card, frame chrome): the native element, no kit class. */
export function Button({ variant = 'quiet', className, action, iconOnly = false, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  action?: ButtonAction
  iconOnly?: boolean
  'data-tooltip'?: string
  ref?: Ref<HTMLButtonElement>
}) {
  // The caller's type (or the form default) is preserved: no behavior change.
  const pressed = rest['aria-pressed']
  const StateIcon = pressed === true || pressed === 'true' ? SquareCheck : Square
  const words = children ?? (action && ACTION_WORDS[action])
  return <button
    aria-label={iconOnly ? rest['data-tooltip'] : undefined}
    className={join(variant !== 'bare' && 'kit-button', variant !== 'bare' && `kit-button--${variant}`,
      (action !== undefined || pressed !== undefined) && 'kit-button--icon', iconOnly && 'kit-button--icon-only',
      iconOnly && (action === 'pin' || action === 'unpin') && 'kit-button--pin', className) || undefined}
    {...rest}
  >
    {action && <ActionIcon action={action} />}
    {!action && pressed !== undefined && <StateIcon className="kit-icon" aria-hidden="true" focusable="false" />}
    {iconOnly ? <span className="visually-hidden">{words}</span> : words}
  </button>
}

/** SD-096 (d): the question names the action and the thing, one line says what is lost, and the
 * answers are Yes and No with no icon (ui-taste 4). */
export function Confirm({ question, lost, disabled, onYes, onNo, className, ...rest }: HTMLAttributes<HTMLDivElement> & {
  question: string
  lost: ReactNode
  disabled?: boolean
  onYes: () => void
  onNo: () => void
}) {
  return <div className={join('kit-confirm', className)} role="dialog" aria-label={question} {...rest}>
    <p><strong>{question}</strong> <small>{lost}</small></p>
    <Button variant="danger" type="button" autoFocus disabled={disabled} data-tooltip-detail={question.replace(/\?$/u, '.')} onClick={onYes}>Yes</Button>
    <Button type="button" data-tooltip-detail="Leave it as it is." onClick={onNo}>No</Button>
  </div>
}

/** A Button that asks first: its click opens the question and Yes runs `onConfirm`. */
export function ConfirmButton({ question, lost, onConfirm, ...rest }: Omit<Parameters<typeof Button>[0], 'onClick'> & {
  question: string
  lost: ReactNode
  onConfirm: () => void
}) {
  const [asking, setAsking] = useState(false)
  return <>
    <Button aria-haspopup="dialog" aria-expanded={asking} {...rest} onClick={() => setAsking(true)} />
    {asking && <Confirm question={question} lost={lost} disabled={rest.disabled} onYes={() => { setAsking(false); onConfirm() }} onNo={() => setAsking(false)} />}
  </>
}

export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & {
  ref?: Ref<HTMLSelectElement>
}) {
  return <span className="kit-select-wrap">
    <select className={join('kit-select', className)} {...rest} />
    <ChevronsUpDown className="kit-icon" aria-hidden="true" focusable="false" />
  </span>
}

/** A row of Buttons where one is pressed or selected; the pressed look reads aria-pressed / aria-selected. */
export function Segmented({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={join('kit-segmented', className)} {...rest} />
}

export function Toggle({ className, ...rest }: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  ref?: Ref<HTMLInputElement>
}) {
  return <span className="kit-toggle-wrap">
    <input type="checkbox" className={join('kit-toggle', className)} {...rest} />
    <Square className="kit-icon kit-toggle-off" aria-hidden="true" focusable="false" />
    <SquareCheck className="kit-icon kit-toggle-on" aria-hidden="true" focusable="false" />
  </span>
}

export function TextField({ className, ...rest }: InputHTMLAttributes<HTMLInputElement> & {
  ref?: Ref<HTMLInputElement>
}) {
  return <input className={join('kit-field', className)} {...rest} />
}

export function FileField(props: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  return <span className="kit-file-wrap">
    <input {...props} type="file" />
    <ActionIcon action="open" />
  </span>
}

export function TextArea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & {
  ref?: Ref<HTMLTextAreaElement>
}) {
  return <textarea className={join('kit-field', className)} {...rest} />
}

export function Chip({ className, ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return <span className={join('kit-chip', className)} {...rest} />
}

/** A module's own title row: mono-caps title, optional quiet detail, actions on the right. */
export function ModuleHeader({ title, detail, children, className, ...rest }: Omit<HTMLAttributes<HTMLElement>, 'title'> & {
  title: ReactNode
  detail?: ReactNode
}) {
  return <header className={join('kit-module-header', className)} {...rest}>
    <h2>{title}</h2>
    {detail !== undefined && <span className="kit-module-header__detail">{detail}</span>}
    {children !== undefined && <div className="kit-module-header__actions">{children}</div>}
  </header>
}

export function EmptyState({ label, title, children, className, ...rest }: Omit<HTMLAttributes<HTMLDivElement>, 'title'> & {
  label?: ReactNode
  title: ReactNode
}) {
  return <div className={join('kit-empty', className)} {...rest}>
    {label !== undefined && <span className="kit-empty__label">{label}</span>}
    <strong>{title}</strong>
    {children}
  </div>
}
