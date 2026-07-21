/**
 * An honest placeholder for a module that has no backend yet.
 *
 * The alternative - rendering an empty Insights page - is indistinguishable
 * from a working module with nothing to show, and would quietly teach the
 * user that Sentinel has no insights rather than that it hasn't been built.
 */
export function NotBuiltModule({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-dashed border-border p-10 text-center">
      <p className="text-[13px] font-semibold text-ink-dim">{label} isn't built yet</p>
      <p className="mx-auto mt-2 max-w-md text-[12px] leading-relaxed text-ink-faint">
        This module is part of the planned channel experience but has no backend behind it today. It's listed here so the
        structure is visible — not because there's data waiting. Nothing is hidden from you.
      </p>
    </div>
  );
}
