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
 *  - An action is written as `<Action kind="done" />`, never as a bespoke
 *    button or an underlined word. The catalogue in Action.tsx owns how
 *    every verb looks, so Done cannot differ between two pages.
 *  - A list of things is `ItemList` + `ItemRow`. Explanatory prose goes in
 *    the row's `details` slot and stays collapsed - there is no prop for a
 *    paragraph, which is what keeps pages scannable.
 */
export { cn } from "./cn";
export { BASE as BUTTON_BASE, Button, ButtonLink, SIZES as BUTTON_SIZES } from "./Button";
export type { ButtonSize, ButtonVariant } from "./Button";
export { Action, ActionGroup, ActionLink } from "./Action";
export type { ActionKind } from "./Action";
export { Meta, MetaCount, MetaWrap } from "./Meta";
export { ItemList, ItemRow } from "./ItemRow";
export { FilterChips } from "./Filters";
export { SeverityFilter } from "./SeverityFilter";
export type { FilterOption } from "./SeverityFilter";
export { Card, CardButton, CardGrid, CardHeader, CardLink } from "./Card";
export { Badge, StatusDot } from "./Badge";
export type { Tone } from "./Badge";
export { Field, Input, Select, Textarea } from "./Field";
export { EmptyState } from "./EmptyState";
export { Divider, PageHeader, Section } from "./Layout";
export { Tabs } from "./Tabs";
export type { TabItem } from "./Tabs";
export { TabBar } from "./TabBar";
export type { TabBarItem } from "./TabBar";
export { Rows, TableWrap, Td, Th, Tr } from "./Table";
export { Icon } from "./Icon";
export { Overflow, OverflowItem } from "./Overflow";
export type { IconName } from "./Icon";
export { Tooltip } from "./Tooltip";
export { LoadingBlock, Spinner } from "./Spinner";
export { Skeleton, SkeletonCard, SkeletonRows, SkeletonText } from "./Skeleton";
export { ToastProvider, useToast } from "./Toast";
