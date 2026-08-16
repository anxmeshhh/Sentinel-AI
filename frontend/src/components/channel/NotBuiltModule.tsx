import { EmptyState } from "../ui";

/**
 * An honest placeholder for a module that has no backend yet.
 *
 * The alternative - rendering an empty Insights page - is indistinguishable
 * from a working module with nothing to show, and would quietly teach the
 * user that Sentinel has no insights rather than that it hasn't been built.
 */
export function NotBuiltModule({ label }: { label: string }) {
  return (
    <EmptyState
      title={`${label} isn't built yet`}
      description="This module is part of the planned channel experience but has no backend behind it today. It's listed so the structure is visible - not because there's data waiting. Nothing is hidden from you."
    />
  );
}
