import { createFileRoute, useRouter } from "@tanstack/react-router";

import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  PageHeader,
  SectionLabel,
} from "@/components/sentinel/primitives";
import { useAuth, useWorkspace } from "@/lib/auth";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings · Sentinel" },
      { name: "description", content: "Your account, workspace and how Sentinel behaves." },
    ],
  }),
  component: SettingsPage,
});

/**
 * Only what is real.
 *
 * The behaviour section states invariants rather than offering toggles: these
 * are enforced by the Action Registry on the server, and a switch here that did
 * not change them would be a lie about how much control the user has.
 */
function SettingsPage() {
  const { user, logout } = useAuth();
  const { active, workspaces } = useWorkspace();
  const router = useRouter();

  return (
    <div className="max-w-[68ch]">
      <PageHeader title="Settings" caption="Your account, and how Sentinel behaves." />

      <div className="space-y-8">
        <section>
          <SectionLabel>Account</SectionLabel>
          <ul className="mt-2 divide-y divide-border border-y border-border">
            <Row label="Name" value={user?.name ?? "—"} />
            <Row label="Email" value={user?.email ?? "—"} />
            <Row
              label="Email verified"
              value={user?.email_verified ? "Yes" : "Not verified"}
            />
          </ul>
        </section>

        <section>
          <SectionLabel>Context</SectionLabel>
          <ul className="mt-2 divide-y divide-border border-y border-border">
            <li className="flex flex-wrap items-center justify-between gap-3 py-3">
              <span className="t-small text-ink">Active</span>
              <span className="t-caption flex items-center gap-2 text-ink-faint">
                <Dot
                  color={active?.kind === "personal" ? "var(--ctx-personal)" : "var(--ctx-org)"}
                />
                {active?.name ?? "—"}
              </span>
            </li>
            <Row
              label="You belong to"
              value={`${workspaces.length} ${workspaces.length === 1 ? "workspace" : "workspaces"}`}
            />
            <Row
              label="Visibility"
              value={
                active?.kind === "personal"
                  ? "Private to you"
                  : `Shared · you are ${active?.role ?? "a member"}`
              }
            />
          </ul>
        </section>

        <section>
          <SectionLabel>How Sentinel behaves</SectionLabel>
          <ul className="mt-2 divide-y divide-border border-y border-border">
            <Row
              label="Detection"
              value="Deterministic — rules, never a model"
            />
            <Row
              label="Explanations"
              value="Written only from findings Sentinel already established"
            />
            <Row
              label="Anything that leaves Sentinel"
              value="Always previewed and confirmed by you"
            />
            <Row
              label="Undo"
              value="Offered only where a real inverse exists"
            />
            <Row label="New memories" value="Announced once, when first formed" />
          </ul>
          <p className="t-caption mt-3 text-ink-faint">
            These are enforced by Sentinel itself, not preferences — which is why there is nothing
            here to switch off.
          </p>
        </section>

        <section>
          <SectionLabel>Session</SectionLabel>
          <div className="mt-3 flex flex-wrap gap-2">
            <ButtonSecondary
              onClick={() => {
                logout();
                router.navigate({ to: "/login" });
              }}
            >
              Sign out
            </ButtonSecondary>
            <ButtonGhost onClick={() => router.navigate({ to: "/connections" })}>
              Manage connections
            </ButtonGhost>
          </div>
        </section>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <span className="t-small text-ink">{label}</span>
      <span className="t-caption text-ink-faint">{value}</span>
    </li>
  );
}
