/** PLAN M3UI: the one control kit. Every control in the app is one of these; the kit lint keeps it so.
 * Each part is the native element plus the kit class: props, handlers, aria and test ids pass straight
 * through, so swapping a raw control for its kit part changes its look and nothing else.
 * The module frame header is RackModuleFrame and the hover tip is ControlTooltip; both were already one. */
import type {
  ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, Ref,
  SelectHTMLAttributes, TextareaHTMLAttributes,
} from 'react'

function join(...names: (string | false | undefined)[]): string {
  return names.filter(Boolean).join(' ')
}

export type ButtonVariant = 'primary' | 'quiet' | 'danger' | 'bare'

/** `bare` is a button that wears its content's look (a row, a card, frame chrome): the native element, no kit class. */
export function Button({ variant = 'quiet', className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  ref?: Ref<HTMLButtonElement>
}) {
  // The caller's type (or the form default) is preserved: no behavior change.
  return <button className={variant === 'bare' ? className : join('kit-button', `kit-button--${variant}`, className)} {...rest} />
}

export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & {
  ref?: Ref<HTMLSelectElement>
}) {
  return <select className={join('kit-select', className)} {...rest} />
}

/** A row of Buttons where one is pressed or selected; the pressed look reads aria-pressed / aria-selected. */
export function Segmented({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={join('kit-segmented', className)} {...rest} />
}

export function Toggle({ className, ...rest }: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  ref?: Ref<HTMLInputElement>
}) {
  return <input type="checkbox" className={join('kit-toggle', className)} {...rest} />
}

export function TextField({ className, ...rest }: InputHTMLAttributes<HTMLInputElement> & {
  ref?: Ref<HTMLInputElement>
}) {
  return <input className={join('kit-field', className)} {...rest} />
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
