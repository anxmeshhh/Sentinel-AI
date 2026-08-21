import type { ReactNode } from "react";

import { Button, type ButtonVariant } from "./Button";
import { Icon, type IconName } from "./Icon";
import { cn } from "./cn";

/**
 * The one global action system.
 *
 * The audit found 211 raw `<button>` elements, 91 of them bare underlined
 * text links. "Done" was a link on the dashboard, a bordered button on a
 * provider page and an underlined word in a panel - three treatments for one
 * verb, which is why the product read as inconsistent even though a Button
 * component already existed.
 *
 * The fix is not another button variant. It is removing the choice: an action
 * is named by what it DOES, and this catalogue owns how that looks. Callers
 * write `<Action kind="done" onClick={…} />` and cannot make Done look
 * different here than it does there.
 *
 * Hierarchy, one rule:
 *   primary    the single recommended next step  (Take action, Confirm)
 *   secondary  the ordinary things  (Details, Create, Edit)
 *   ghost      the quiet outs  (Dismiss, Cancel)
 *   danger     destructive and irreversible
 *
 * Three verbs carry their own colour rather than the neutral secondary tone:
 * Done (green), Snooze (blue) and Open (purple). That is a deliberate,
 * explicit exception to "icons stay monochrome" - every other action still
 * reserves colour for status, but these three are frequent enough, and
 * different enough in kind, that a person scanning a row benefits from
 * telling them apart at a glance. The exception lives in exactly one place
 * (TONE_CLASS below), so it cannot drift into a fourth treatment per page.
 */
export type ActionKind =
  | "done"
  | "snooze"
  | "open"
  | "details"
  | "dismiss"
  | "takeAction"
  | "confirm"
  | "cancel"
  | "undo"
  | "create"
  | "edit"
  | "retry";

interface ActionSpec {
  label: string;
  icon?: IconName;
  variant: ButtonVariant;
}

const CATALOGUE: Record<ActionKind, ActionSpec> = {
  done: { label: "Done", icon: "check", variant: "secondary" },
  snooze: { label: "Snooze", icon: "clock", variant: "secondary" },
  open: { label: "Open", icon: "external", variant: "secondary" },
  details: { label: "Details", variant: "secondary" },
  dismiss: { label: "Dismiss", icon: "close", variant: "ghost" },
  takeAction: { label: "Take action", icon: "sparkle", variant: "primary" },
  confirm: { label: "Confirm", icon: "check", variant: "primary" },
  cancel: { label: "Cancel", variant: "ghost" },
  undo: { label: "Undo", icon: "refresh", variant: "ghost" },
  create: { label: "Create", icon: "plus", variant: "secondary" },
  edit: { label: "Edit", variant: "secondary" },
  retry: { label: "Try again", icon: "refresh", variant: "secondary" },
};

/** `!`-prefixed so these reliably win over `secondary`'s own
 *  `text-ink-dim border-border` - Tailwind resolves same-specificity
 *  utilities by the order it wrote them into the stylesheet, not by the
 *  order they appear in a className string, so a plain override is not
 *  dependable here. The important-marked utility is. */
const TONE_CLASS: Partial<Record<ActionKind, string>> = {
  done: "!border-good/35 !text-good hover:!border-good/60 hover:!bg-good/10",
  snooze: "!border-watch/35 !text-watch hover:!border-watch/60 hover:!bg-watch/10",
  open: "!border-accent/35 !text-accent-text hover:!border-accent/60 hover:!bg-accent/10",
};

export function Action({
  kind,
  label,
  onClick,
  disabled,
  loading,
  className,
}: {
  kind: ActionKind;
  /** Override only when the verb needs an object ("Mark all done"). The
   *  styling never changes with it. */
  label?: string;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  className?: string;
}) {
  const spec = CATALOGUE[kind];
  return (
    <Button
      size="sm"
      variant={spec.variant}
      onClick={onClick}
      disabled={disabled}
      loading={loading}
      className={cn(TONE_CLASS[kind], className)}
    >
      {spec.icon && !loading && <Icon name={spec.icon} size={13} />}
      {label ?? spec.label}
    </Button>
  );
}

/** The same action as a link, for the cases that navigate rather than act. */
export function ActionLink({
  kind,
  to,
  label,
  className,
}: {
  kind: ActionKind;
  to: string;
  label?: string;
  className?: string;
}) {
  const spec = CATALOGUE[kind];
  return (
    <a
      href={to}
      target={kind === "open" ? "_blank" : undefined}
      rel={kind === "open" ? "noreferrer" : undefined}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 text-caption font-medium transition-colors duration-200 ease-out",
        TONE_CLASS[kind] ??
          (spec.variant === "primary"
            ? "border-transparent bg-ink text-ground hover:bg-white"
            : "border-border text-ink-dim hover:border-border-strong hover:text-ink"),
        className,
      )}
    >
      {spec.icon && <Icon name={spec.icon} size={13} />}
      {label ?? spec.label}
    </a>
  );
}

/**
 * The row of actions on an item.
 *
 * Exists so actions are always in the same place at the same spacing, and so
 * a row that is not hovered stays quiet. Density comes from actions being
 * present but recessive, not from removing them.
 */
export function ActionGroup({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("flex flex-none items-center gap-1.5", className)}>{children}</div>;
}
