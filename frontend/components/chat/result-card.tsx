import { ChevronDown, FileJson, Heart, User } from "lucide-react";

import { ChatMessage } from "@/types/chat";
import { cn } from "@/lib/utils";
import { FeedbackComponent } from "@/components/ui/feedback-component";
import { submitFeedback } from "@/lib/api";

type ResultCardProps = {
  message: ChatMessage;
  sessionId: string;
};

type ParsedSections = {
  intro: string[];
  basics: string[];
  days: Array<{ title: string; lines: string[] }>;
  budget: string[];
  reminders: Array<{ title: string; lines: string[] }>;
  leftovers: string[];
};

const REMINDER_TITLES = ["提醒事项", "注意事项", "餐饮补充", "雨天调整", "雨天建议", "交通补充", "美食推荐"];

function getResponseText(raw: Record<string, unknown> | undefined) {
  if (!raw) {
    return "";
  }

  const candidates = [raw["系统答复"], raw["绯荤粺绛斿悗"], raw["answer"], raw["response"], raw["message"]];
  return (candidates.find((value) => typeof value === "string") as string | undefined) || "";
}

function isListLine(line: string) {
  return /^([0-9]+[.)]|[-•])\s+/.test(line);
}

function parseStructuredText(text: string): ParsedSections {
  const normalized = text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const sections: ParsedSections = {
    intro: [],
    basics: [],
    days: [],
    budget: [],
    reminders: [],
    leftovers: [],
  };

  let cursor:
    | "intro"
    | "basics"
    | "budget"
    | "leftovers"
    | { type: "day"; index: number }
    | { type: "reminder"; index: number } = "intro";

  normalized.forEach((line) => {
    if (/^基础信息[:：]?$/.test(line)) {
      cursor = "basics";
      return;
    }

    if (/^Day\s*\d+/i.test(line) || /^第[一二三四五六七八九十\d]+天/.test(line)) {
      sections.days.push({ title: line, lines: [] });
      cursor = { type: "day", index: sections.days.length - 1 };
      return;
    }

    if (/^预算拆分[:：]?$/.test(line) || /^预算[:：]?$/.test(line)) {
      cursor = "budget";
      return;
    }

    if (REMINDER_TITLES.some((title) => line.startsWith(title))) {
      sections.reminders.push({ title: line, lines: [] });
      cursor = { type: "reminder", index: sections.reminders.length - 1 };
      return;
    }

    if (cursor === "intro") {
      sections.intro.push(line);
      return;
    }

    if (cursor === "basics") {
      sections.basics.push(line);
      return;
    }

    if (cursor === "budget") {
      sections.budget.push(line);
      return;
    }

    if (cursor === "leftovers") {
      sections.leftovers.push(line);
      return;
    }

    if (cursor.type === "day") {
      sections.days[cursor.index]?.lines.push(line);
      return;
    }

    if (cursor.type === "reminder") {
      sections.reminders[cursor.index]?.lines.push(line);
    }
  });

  const matched = sections.basics.length > 0 || sections.days.length > 0 || sections.budget.length > 0 || sections.reminders.length > 0;
  if (!matched) {
    sections.leftovers = normalized;
  }

  return sections;
}

function SectionBlock({ title, lines }: { title: string; lines: string[]; tone?: "default" | "success" | "warning" }) {
  const toneClassName = "border-border/70 bg-slate-50/80 dark:bg-slate-900/70";

  return (
    <section className={cn("rounded-2xl border p-4 md:p-5", toneClassName)}>
      <h3 className="mb-3 text-sm font-semibold tracking-wide text-slate-900 dark:text-slate-50">{title}</h3>
      <div className="space-y-2">
        {lines.map((line, index) => {
          const listStyle = isListLine(line);
          return (
            <p
              key={`${line}-${index}`}
              className={cn(
                "whitespace-pre-wrap break-words text-sm leading-7 text-slate-700 dark:text-slate-200",
                listStyle && "pl-1 font-medium text-slate-800 dark:text-slate-100"
              )}
            >
              {line}
            </p>
          );
        })}
      </div>
    </section>
  );
}

export function ResultCard({ message, sessionId }: ResultCardProps) {
  const responseText = getResponseText(message.raw) || message.content;
  const parsed = parseStructuredText(responseText);
  const showStructured = parsed.basics.length > 0 || parsed.days.length > 0 || parsed.budget.length > 0 || parsed.reminders.length > 0;

  return (
    <div className="rounded-3xl border border-border/70 bg-card p-5 shadow-soft md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-700 dark:text-sky-300">旅游规划结果</div>
          <div className="mt-1 text-sm text-muted-foreground">根据您的需求生成的旅行规划</div>
        </div>
        {message.timestamp ? <div className="text-xs text-muted-foreground">{message.timestamp}</div> : null}
      </div>

      <div className="mt-5 space-y-6">
        {showStructured ? (
          <>
            {parsed.intro.length > 0 ? <SectionBlock title="概览" lines={parsed.intro} /> : null}
            {parsed.basics.length > 0 ? <SectionBlock title="基础信息" lines={parsed.basics} /> : null}

            {/* 每日行程 */}
            {parsed.days.length > 0 && (
              <div className="space-y-4">
                {parsed.days.map((day, index) => (
                  <SectionBlock key={index} title={day.title || `第${index + 1}天`} lines={day.lines} />
                ))}
              </div>
            )}

            {parsed.budget.length > 0 ? <SectionBlock title="预算分析" lines={parsed.budget} /> : null}

            {parsed.reminders.length > 0 ? (
              <section className="space-y-3">
                {parsed.reminders.map((block, index) => (
                  <SectionBlock key={index} title={block.title} lines={block.lines} />
                ))}
              </section>
            ) : null}

            {parsed.leftovers.length > 0 ? <SectionBlock title="补充说明" lines={parsed.leftovers} /> : null}
          </>
        ) : (
          <div className="whitespace-pre-wrap break-words rounded-2xl bg-slate-50 p-4 text-sm leading-7 text-slate-700 dark:bg-slate-900/70 dark:text-slate-200">
            {responseText}
          </div>
        )}

        {/* 后续交互选项 */}
        <div className="rounded-2xl border border-border/70 bg-slate-50/80 p-4 dark:bg-slate-900/70">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50 mb-3">继续调整行程</h3>
          <div className="grid grid-cols-2 gap-3">
            <button
              className="flex flex-col items-center justify-center gap-2 p-3 rounded-xl border border-border/70 bg-white/80 hover:bg-sky-50 transition-colors dark:bg-slate-800/80 dark:hover:bg-slate-700/80"
            >
              <span className="text-xs font-medium text-slate-700 dark:text-slate-200">修改预算</span>
            </button>
            <button
              className="flex flex-col items-center justify-center gap-2 p-3 rounded-xl border border-border/70 bg-white/80 hover:bg-sky-50 transition-colors dark:bg-slate-800/80 dark:hover:bg-slate-700/80"
            >
              <span className="text-xs font-medium text-slate-700 dark:text-slate-200">调整天数</span>
            </button>
            <button
              className="flex flex-col items-center justify-center gap-2 p-3 rounded-xl border border-border/70 bg-white/80 hover:bg-sky-50 transition-colors dark:bg-slate-800/80 dark:hover:bg-slate-700/80"
            >
              <Heart className="h-5 w-5 text-sky-600 dark:text-sky-400" />
              <span className="text-xs font-medium text-slate-700 dark:text-slate-200">更改风格</span>
            </button>
            <button
              className="flex flex-col items-center justify-center gap-2 p-3 rounded-xl border border-border/70 bg-white/80 hover:bg-sky-50 transition-colors dark:bg-slate-800/80 dark:hover:bg-slate-700/80"
            >
              <User className="h-5 w-5 text-sky-600 dark:text-sky-400" />
              <span className="text-xs font-medium text-slate-700 dark:text-slate-200">调整人群</span>
            </button>
          </div>
        </div>

        {message.raw ? (
          <details className="group rounded-2xl border border-border/50 bg-slate-50/60 px-4 py-3 text-sm dark:bg-slate-900/50">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium text-muted-foreground">
              <span className="inline-flex items-center gap-2">
                <FileJson className="h-4 w-4" />
                查看原始 JSON
              </span>
              <ChevronDown className={cn("h-4 w-4 transition-transform group-open:rotate-180")} />
            </summary>
            <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">
              {JSON.stringify(message.raw, null, 2)}
            </pre>
          </details>
        ) : null}

        {/* 用户反馈组件 */}
        <FeedbackComponent
          onSubmit={async (feedback) => {
            try {
              await submitFeedback(sessionId, feedback.rating, feedback.comment);
            } catch (error) {
              console.error("Feedback submission failed:", error);
              throw error;
            }
          }}
        />
      </div>
    </div>
  );
}
