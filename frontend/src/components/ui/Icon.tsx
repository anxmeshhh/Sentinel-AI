import { cn } from "./cn";

/** One stroke icon set.
 *
 *  The audit found 14 inline <svg> blocks and 25 emoji/text glyphs standing
 *  in for icons - emoji render differently per OS and carry their own
 *  colour, which is why the UI never looked like one product. These share a
 *  24px grid, 1.5 stroke, and `currentColor`, so an icon always matches the
 *  text it sits beside.
 *
 *  Deliberately small: every icon here is one actually used by Sentinel. */
const PATHS = {
  chevronRight: "M9 6l6 6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  check: "M4 12.5l5 5L20 6.5",
  plus: "M12 5v14M5 12h14",
  close: "M6 6l12 12M18 6L6 18",
  menu: "M3 6h18M3 12h18M3 18h18",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35",
  external: "M14 4h6v6M20 4L10 14M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6",
  refresh: "M20 11A8 8 0 0 0 6.3 6.3L4 8.5M4 13a8 8 0 0 0 13.7 4.7L20 15.5M4 4v4.5h4.5M20 20v-4.5h-4.5",
  lock: "M6 11V8a6 6 0 1 1 12 0v3M5 11h14v9H5z",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H1a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 2.6 7a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H7a1.7 1.7 0 0 0 1-1.5V1a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V7a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  hash: "M4 9h16M4 15h16M10 3L8 21M16 3l-2 18",
  alert: "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  mail: "M4 5h16v14H4zM4 6l8 6 8-6",
  calendar: "M8 3v4M16 3v4M4 9h16M5 5h14v15H5z",
  file: "M14 3v5h5M14 3H6v18h12V8z",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  arrowRight: "M5 12h14M13 6l6 6-6 6",
  chevronLeft: "M15 6l-6 6 6 6",
  // Sidebar and card iconography. Same 24px grid and 1.5 stroke as the rest,
  // so an icon always matches the text beside it.
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  activity: "M3 12h4l3 8 4-16 3 8h4",
  layers: "M12 3l9 5-9 5-9-5 9-5zM3 14l9 5 9-5",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  brain: "M12 5a3 3 0 0 0-6 0v1a3 3 0 0 0-1 5.8V13a3 3 0 0 0 4 2.8V17a2 2 0 1 0 4 0V5zM12 5a3 3 0 0 1 6 0v1a3 3 0 0 1 1 5.8V13a3 3 0 0 1-4 2.8V17a2 2 0 1 1-4 0",
  flag: "M5 21V4M5 4h11l-2 4 2 4H5",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9a2.5 2.5 0 1 1 3.4 2.3c-.6.3-.9.8-.9 1.4v.3M12 17h.01",
  more: "M12 6h.01M12 12h.01M12 18h.01",
  mic: "M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3zM19 11a7 7 0 0 1-14 0M12 18v3",
  send: "M4 12l16-8-6 16-2.5-6z",
  sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z",
  video: "M15 8H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V9a1 1 0 0 0-1-1zM16 11l5-3v8l-5-3",
  square: "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z",
  sliders: "M4 8h10M18 8h2M4 16h4M12 16h8M14 5v6M8 13v6",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  size = 16,
  className,
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={cn("flex-none", className)}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
