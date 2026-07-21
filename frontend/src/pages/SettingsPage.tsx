import { BackNav } from "../components/BackNav";

const AGENTS = [
  { name: "Engineering", desc: "GitHub bottlenecks, hotspots, inactive contributors, risky deploys", tag: "PHASE 1", on: true },
  { name: "Communication", desc: "Stale flagged mail, spam surges, calendar overload — from Gmail/Calendar", tag: "PHASE 2", on: true },
  { name: "Executive", desc: "Synthesizes every agent's findings into the daily brief", tag: "ALWAYS ON", on: true },
  { name: "Project", desc: "Jira / Linear sprint risk & deadline-slip prediction", tag: "PHASE 2", on: false },
  { name: "Knowledge", desc: "Stale or missing docs across Notion / Confluence", tag: "PHASE 3", on: false },
  { name: "DevOps · Security · Finance", desc: "Deploy risk, secret exposure, cost anomalies", tag: "PHASE 4", on: false },
  { name: "HR Wellbeing", desc: "Team-level workload patterns only — never individual judgment. Opt-in, off by default.", tag: "OPT-IN", on: false },
];

export function SettingsPage() {
  return (
    <div className="max-w-2xl">
      <BackNav back={{ to: "/", label: "Dashboard" }} />
      <h1 className="mb-1 text-h2 font-semibold text-balance">Agents</h1>
      <p className="mb-7 text-body text-ink-dim">
        Which agents are allowed to run. Connections live on the Dashboard now.
      </p>

      <div className="rounded-lg border border-border bg-surface shadow-card">
        {AGENTS.map((agent) => (
          <div key={agent.name} className="flex items-center gap-3.5 border-b border-border p-3 last:border-b-0">
            <div>
              <div className="text-body font-semibold">{agent.name}</div>
              <div className="mt-0.5 text-small text-ink-faint">{agent.desc}</div>
            </div>
            <span className="ml-auto whitespace-nowrap rounded-full border border-border px-2 py-[3px] text-micro text-ink-faint">
              {agent.tag}
            </span>
            <div className={`h-[19px] w-[34px] flex-none rounded-full ${agent.on ? "bg-accent" : "bg-border"}`}>
              <div
                className={`h-[15px] w-[15px] translate-y-[2px] rounded-full bg-surface transition-transform ${
                  agent.on ? "translate-x-[17px]" : "translate-x-[2px]"
                }`}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
