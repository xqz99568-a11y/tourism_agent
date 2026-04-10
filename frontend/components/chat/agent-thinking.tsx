"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Bot, Loader2, CheckCircle2, Circle, XCircle } from "lucide-react";

interface ProcessingState {
  phase: string;
  message: string;
  completed: boolean;
}

interface AgentThinkingProps {
  states: ProcessingState[];
}

const PHASE_ICONS: Record<string, React.ReactNode> = {
  analyzing: <Bot className="w-4 h-4" />,
  planning: <Bot className="w-4 h-4" />,
  searching: <Bot className="w-4 h-4" />,
  calculating: <Bot className="w-4 h-4" />,
  generating: <Bot className="w-4 h-4" />,
  reviewing: <Bot className="w-4 h-4" />,
  synthesizing: <Bot className="w-4 h-4" />,
};

const PHASE_LABELS: Record<string, string> = {
  analyzing: "意图分析",
  planning: "任务规划",
  intent_parsing: "意图解析",
  task_planning: "任务规划",
  parallel_execution: "并行执行",
  result_aggregation: "结果聚合",
  quality_review: "质量审查",
  response_synthesis: "响应生成",
  searching: "搜索中",
  calculating: "计算中",
  generating: "生成中",
  reviewing: "审查中",
  synthesizing: "综合中",
};

export function AgentThinking({ states }: AgentThinkingProps) {
  if (states.length === 0) return null;

  const currentState = states[states.length - 1];

  return (
    <div className="flex gap-3">
      <Avatar className="w-8 h-8 shrink-0">
        <AvatarFallback className="bg-primary text-primary-foreground">
          <Bot className="w-4 h-4" />
        </AvatarFallback>
      </Avatar>

      <div className="flex flex-col gap-2 max-w-[80%]">
        {/* Processing animation */}
        <div className="bg-muted rounded-2xl rounded-tl-sm px-4 py-3">
          <div className="flex items-center gap-2 mb-2">
            {currentState.completed ? (
              <CheckCircle2 className="w-4 h-4 text-green-500" />
            ) : (
              <Loader2 className="w-4 h-4 animate-spin text-primary" />
            )}
            <span className="text-sm font-medium">
              {PHASE_LABELS[currentState.phase] || currentState.phase}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">
            {currentState.message}
          </p>

          {/* Progress dots */}
          {!currentState.completed && (
            <div className="flex gap-1 mt-2">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"
                  style={{
                    animationDelay: `${i * 200}ms`,
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {/* Phase history */}
        {states.length > 1 && (
          <div className="flex flex-wrap gap-2">
            {states.slice(0, -1).map((state, i) => (
              <div
                key={i}
                className="flex items-center gap-1 px-2 py-1 rounded-full bg-secondary text-secondary-foreground text-xs"
              >
                <CheckCircle2 className="w-3 h-3 text-green-500" />
                {PHASE_LABELS[state.phase] || state.phase}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
