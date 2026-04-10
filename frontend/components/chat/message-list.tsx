"use client";

import { useEffect, useRef } from "react";
import { Compass, Sparkles } from "lucide-react";

import { MessageBubble } from "@/components/chat/message-bubble";
import { ResultCard } from "@/components/chat/result-card";
import { ChatMessage } from "@/types/chat";

type MessageListProps = {
  messages: ChatMessage[];
  onExampleClick: (value: string) => void | Promise<void>;
  sessionId: string;
};

const EXAMPLES = [
  "广州出发去杭州玩3天，2个人，预算3000，住西湖附近",
  "我想去杭州玩，帮我做个计划。",
  "去桂林玩几天合适？预算2000左右",
];

export function MessageList({ messages, onExampleClick, sessionId }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-4 py-8 md:px-6">
        <div className="w-full max-w-2xl rounded-[32px] border border-border/70 bg-white/75 p-6 text-center shadow-soft backdrop-blur dark:bg-slate-950/70 md:p-10">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-200">
            <Compass className="h-7 w-7" />
          </div>
          <h2 className="mt-5 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">娆㈣繋浣跨敤鏃呮父瑙勫垝 Agent</h2>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-7 text-muted-foreground">
            鐢ㄨ嚜鐒惰瑷€鎻忚堪浣犵殑鏃呰闇€姹傦紝鎴戜細甯綘鐢熸垚鏃呰鏂规
          </p>
          <div className="mt-8 grid gap-3 text-left">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => void onExampleClick(example)}
                className="rounded-2xl border border-border/70 bg-background px-4 py-4 text-sm leading-6 text-slate-700 transition-colors hover:border-sky-200 hover:bg-sky-50/70 hover:text-sky-900 dark:text-slate-200 dark:hover:border-sky-900 dark:hover:bg-sky-950/20 dark:hover:text-sky-100"
              >
                <span className="flex items-start gap-3">
                  <Sparkles className="mt-1 h-4 w-4 shrink-0 text-sky-600 dark:text-sky-300" />
                  <span className="break-words">{example}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto px-4 py-5 md:px-6">
      {messages.map((message) =>
        message.role === "assistant" ? (
          <ResultCard key={message.id} message={message} sessionId={sessionId} />
        ) : (
          <MessageBubble key={message.id} message={message} />
        ),
      )}
      <div ref={bottomRef} />
    </div>
  );
}
