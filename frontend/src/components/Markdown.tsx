import type { ReactNode } from "react";

// A small, dependency-free renderer for the subset of markdown Sentinel
// actually produces: paragraphs, headings, bold, links, bullet lists,
// numbered lists. Deliberately does not handle tables - those render
// unreadably in a narrow chat column regardless of markdown support, so
// callers (the AI Command system prompt, the HTML-email-to-markdown
// converter) are told to use lists instead.
//
// Links are the load-bearing feature here: every external resource Sentinel
// surfaces (an email, a calendar event, a Drive file, a link inside an
// email body) is a real [text](url) pointing at the resource's actual home
// on its own platform - Sentinel never opens or renders the resource
// itself, only links out to it.
export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    const heading = /^(#{1,6})\s+(.*)/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const Tag = (level <= 2 ? "h3" : "h4") as "h3" | "h4";
      const cls = level <= 2 ? "mb-1.5 mt-3 text-[13.5px] font-bold text-ink first:mt-0" : "mb-1 mt-2.5 text-[12.5px] font-bold text-ink first:mt-0";
      blocks.push(
        <Tag key={key++} className={cls}>
          {renderInline(heading[2])}
        </Tag>
      );
      i++;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={key++} className="mb-2 ml-4 list-disc space-y-1 last:mb-0">
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item)}</li>
          ))}
        </ul>
      );
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i++;
      }
      blocks.push(
        <ol key={key++} className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item)}</li>
          ))}
        </ol>
      );
      continue;
    }

    if (line.trim() === "" || line.trim() === "---") {
      i++;
      continue;
    }

    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      lines[i].trim() !== "---" &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+[.)]\s+/.test(lines[i]) &&
      !/^#{1,6}\s+/.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="mb-2 last:mb-0">
        {renderInline(paraLines.join(" "))}
      </p>
    );
  }

  return <div>{blocks}</div>;
}

const INLINE_PATTERN = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;

function renderInline(text: string): ReactNode[] {
  return text.split(INLINE_PATTERN).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) {
      const url = cleanLinkUrl(link[2]);
      // Only ever a real external link, target="_blank": a malformed or
      // relative-looking url (e.g. leftover <angle-bracket> wrapping from
      // some markdown source) must never become an in-app navigation -
      // confirmed on a real email where exactly that broke React Router.
      if (url) {
        return (
          <a
            key={i}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-text underline underline-offset-2 hover:opacity-80"
          >
            {link[1]}
          </a>
        );
      }
      return link[1];
    }
    return part;
  });
}

function cleanLinkUrl(raw: string): string | null {
  let url = raw.trim();
  // Some markdown sources wrap the url as <url> or <url> "title" - strip
  // both rather than trust the raw content of a link target.
  const angled = /^<([^>]+)>/.exec(url);
  url = angled ? angled[1] : url.replace(/\s+"[^"]*"$/, "");
  url = url.trim();
  return /^https?:\/\//i.test(url) ? url : null;
}
