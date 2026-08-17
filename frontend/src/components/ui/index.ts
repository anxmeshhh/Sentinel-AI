/**
 * The Sentinel design system.
 *
 * One import site for every shared primitive, so a page can never quietly
 * grow its own version of a button. Tokens (colour, type scale, radius,
 * shadow) live in tailwind.config.ts; the component classes that compose
 * them live in styles/globals.css; this directory is the React surface.
 *
 * Rules that keep it one system:
 *  - Only `Button variant="primary"` is filled. One high-contrast element
 *    per screen.
 *  - Colour means status. A card, input or tab never carries hue.
 *  - Cards are defined by their border, not a fill; fill means hover or
 *    selection.
 *  - Spacing between sections is owned by PageHeader/Section, not by
 *    per-page margins.
 */
export { cn } from "./cn";
export { Button, ButtonLink } from "./Button";
export type { ButtonSize, ButtonVariant } from "./Button";
export { Card, CardButton, CardGrid, CardHeader, CardLink } from "./Card";
export { Badge, StatusDot } from "./Badge";
export type { Tone } from "./Badge";
export { Field, Input, Select, Textarea } from "./Field";
export { EmptyState } from "./EmptyState";
export { Divider, PageHeader, Section } from "./Layout";
export { Tabs } from "./Tabs";
export type { TabItem } from "./Tabs";
export { Rows, TableWrap, Td, Th, Tr } from "./Table";
export { Icon } from "./Icon";
export { Overflow, OverflowItem } from "./Overflow";
export type { IconName } from "./Icon";
export { Tooltip } from "./Tooltip";
export { LoadingBlock, Spinner } from "./Spinner";
export { Skeleton, SkeletonCard, SkeletonRows, SkeletonText } from "./Skeleton";
export { ToastProvider, useToast } from "./Toast";
