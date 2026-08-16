/** Tiny class joiner. Falsy entries drop out, so conditional classes read
 *  as `cond && "..."` without leaving "false" in the DOM. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
