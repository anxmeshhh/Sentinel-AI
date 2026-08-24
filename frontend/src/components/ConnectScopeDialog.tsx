import { Modal } from "./Modal";
import { ScopeBadge, scopeExplanation, type Scope } from "./ScopeBadge";
import { Button } from "./ui";

/** Shown BEFORE the OAuth redirect, never after.
 *
 * Authorizing a mailbox is consequential and irreversible-feeling, and the
 * one question a person actually has is "who will be able to read this?".
 * Answering it on the provider's consent screen is too late - by then
 * they've left Sentinel and the destination is invisible. So the
 * destination is stated here, in Sentinel's own words, with a chance to
 * back out.
 */
export function ConnectScopeDialog({
  providerName,
  scope,
  workspaceName,
  services,
  onConfirm,
  onCancel,
  busy,
}: {
  providerName: string;
  scope: Scope;
  workspaceName?: string;
  services: string[];
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  return (
    <Modal title={`Connect ${providerName}`} onClose={onCancel}>
      <p className="mb-3 text-small text-ink-dim">You are connecting this to:</p>

      <div className="mb-4 rounded-md border border-border bg-ground p-3.5">
        <div className="mb-1.5 text-body font-semibold text-ink">
          {scope === "personal" ? "Your Personal workspace" : workspaceName ?? "This workspace"}
        </div>
        <ScopeBadge scope={scope} workspaceName={workspaceName} />
        <p className="mt-2 text-small leading-relaxed text-ink-faint">{scopeExplanation(scope, workspaceName)}</p>
      </div>

      {services.length > 0 && (
        <div className="mb-4">
          <div className="label-sub mb-1.5">Sentinel will be able to read</div>
          <ul className="flex flex-col gap-1">
            {services.map((s) => (
              <li key={s} className="text-small text-ink-dim">
                · {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mb-4 text-caption leading-relaxed text-ink-faint">
        You can disconnect at any time. {scope === "personal" && "Sentinel never shares a personal connection with a workspace or channel."}
      </p>

      <div className="flex gap-2">
        <button
          onClick={onCancel}
          disabled={busy}
          className="flex-1 rounded-md border border-border py-2.5 text-body text-ink-dim hover:border-crit hover:text-crit disabled:opacity-50"
        >
          Cancel
        </button>
        <Button variant="primary"
          onClick={onConfirm}
          disabled={busy}
          
         className="flex-1">
          {busy ? "Redirecting…" : "Continue"}
        </Button>
      </div>
    </Modal>
  );
}
