/** PLAN M3UI: the one control kit. Every control in the app is one of these; the kit lint keeps it so.
 * Each part is the native element plus the kit class: props, handlers, aria and test ids pass straight
 * through, so swapping a raw control for its kit part changes its look and nothing else.
 * The module frame header is RackModuleFrame and the hover tip is ControlTooltip; both were already one. */
import type {
  ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, Ref,
  SelectHTMLAttributes, TextareaHTMLAttributes,
} from 'react'
import {
  Archive, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, ChevronDown, ChevronUp,
  ChevronsUpDown, Eye, FolderOpen, GripVertical, Keyboard, Maximize, Mic, Minimize, Paperclip,
  Pause, Pencil, Pin, PinOff, Play, Plus, RotateCcw, Save, Search, Send, Settings,
  Square, SquareCheck, Trash2, Undo2, Upload, Volume2, X, ZoomIn, ZoomOut,
} from 'lucide-react'

/** SD-069 / FL-199: one meaning-to-icon table, using the unmodified Lucide set. */
const ACTION_ICONS = {
  send: Send, stop: Square, add: Plus, remove: X, delete: Trash2, refresh: RotateCcw,
  open: FolderOpen, settings: Settings, run: Play, pause: Pause, search: Search,
  close: X, expand: ChevronDown, collapse: ChevronUp, fit: Maximize, minimize: Minimize,
  save: Save, restore: Undo2, back: ArrowLeft, next: ArrowRight, up: ArrowUp,
  latest: ArrowDown, edit: Pencil, pin: Pin, unpin: PinOff, archive: Archive,
  attach: Paperclip, import: Upload, preview: Eye, listen: Mic, speak: Volume2,
  confirm: Check, move: GripVertical, zoomIn: ZoomIn, zoomOut: ZoomOut, typing: Keyboard,
} as const

export type ButtonAction = keyof typeof ACTION_ICONS

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
  return <button
    aria-label={iconOnly ? rest['data-tooltip'] : undefined}
    className={join(variant !== 'bare' && 'kit-button', variant !== 'bare' && `kit-button--${variant}`,
      (action !== undefined || pressed !== undefined) && 'kit-button--icon', iconOnly && 'kit-button--icon-only', className) || undefined}
    {...rest}
  >
    {action && <ActionIcon action={action} />}
    {!action && pressed !== undefined && <StateIcon className="kit-icon" aria-hidden="true" focusable="false" />}
    {iconOnly ? <span className="visually-hidden">{children}</span> : children}
  </button>
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
