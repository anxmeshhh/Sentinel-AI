import { Icon } from "./Icon";
import { Overflow, OverflowItem } from "./Overflow";

export interface FilterOption {
  value: string;
  label: string;
}

/**
 * The compact "Filter" control at the right edge of a tab row.
 *
 * Findings and Situations each had their own copy of this, identical but for
 * one line - how the option's label was derived. Two implementations of one
 * control is how a dropdown ends up opening leftwards on one page and
 * rightwards on the next, so the label is a prop and the control is shared.
 *
 * A dropdown rather than a permanent chip row on purpose: severity only ever
 * narrows a list already on screen, so it earns one click, not a second row
 * of controls competing with the tabs above the content.
 */
export function SeverityFilter({
  value,
  options,
  onChange,
  allLabel = "All severities",
  label = "Filter by severity",
}: {
  value: string | null;
  options: FilterOption[];
  onChange: (value: string | null) => void;
  allLabel?: string;
  label?: string;
}) {
  return (
    <Overflow
      label={label}
      align="right"
      trigger={
        <>
          <Icon name="sliders" size={13} /> Filter
        </>
      }
      triggerClassName="inline-flex h-[30px] items-center gap-1.5 rounded-md border border-border px-3 text-caption font-medium text-ink-dim transition-colors hover:border-border-strong hover:text-ink"
    >
      {(close) => (
        <>
          <OverflowItem
            onClick={() => {
              onChange(null);
              close();
            }}
          >
            {value === null ? "✓ " : ""}
            {allLabel}
          </OverflowItem>
          {options.map((option) => (
            <OverflowItem
              key={option.value}
              onClick={() => {
                onChange(option.value);
                close();
              }}
            >
              {value === option.value ? "✓ " : ""}
              {option.label}
            </OverflowItem>
          ))}
        </>
      )}
    </Overflow>
  );
}
