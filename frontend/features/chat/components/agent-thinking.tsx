"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Bot, CheckCircle2, Circle, Loader2, Sparkles, MapPin, CloudSun, CalendarDays, Wallet } from "lucide-react";
import type { ProcessingState, ThinkingStep } from "@/types";
import { ScrollArea } from "@/components/ui/scroll-area";

// Agent 图标映射
const AGENT_ICONS: Record<string, React.ElementType> = {
  "系统": Sparkles,
  "编排器": Bot,
  "Planner": Sparkles,
  "Attraction": MapPin,
  "Weather": CloudSun,
  "Itinerary": CalendarDays,
  "Budget": Wallet,
  "Review": CheckCircle2,
};

interface AgentThinkingProps {
  states: ProcessingState[];
  thinkingSteps?: ThinkingStep[];
  compact?: boolean;
}

// 类型守卫
function isArray(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

export function AgentThinking({ states, thinkingSteps = [], compact = false }: AgentThinkingProps) {
  const safeStates = isArray(states) ? states : [];
  const safeSteps = isArray(thinkingSteps) ? thinkingSteps : [];
  const hasContent = safeStates.length > 0 || safeSteps.length > 0;

  if (!hasContent) return null;

  return (
    <div
      className={cn(
        "flex flex-col gap-2 animate-in fade-in slide-in-from-bottom-2 duration-300",
        compact ? "py-2" : "p-4"
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Bot className="w-4 h-4 animate-pulse" />
        <span>AI 正在思考...</span>
        <span className="ml-auto text-xs opacity-60">
          {safeSteps.length > 0 ? `${safeSteps.length} 个思考步骤` : ""}
        </span>
      </div>

      {!compact && (
        <ScrollArea className="h-[280px]">
          <div className="space-y-3 pr-4">
            {/* 显示思考步骤详情 */}
            {safeSteps.map((step, index) => {
              const IconComponent = AGENT_ICONS[step.agent || ""] || Bot;
              const isRunning = step.status === "running";
              const isCompleted = step.status === "completed";
              const isFailed = step.status === "failed";

              return (
                <div
                  key={`${step.agent}-${step.step}-${index}`}
                  className={cn(
                    "flex items-start gap-3 p-3 rounded-xl border transition-all",
                    isCompleted
                      ? "bg-green-50/70 border-green-200/50 dark:bg-green-950/20 dark:border-green-800/30"
                      : isRunning
                      ? "bg-blue-50/70 border-blue-200/50 dark:bg-blue-950/20 dark:border-blue-800/30"
                      : isFailed
                      ? "bg-red-50/70 border-red-200/50 dark:bg-red-950/20 dark:border-red-800/30"
                      : "bg-muted/50 border-border/50"
                  )}
                >
                  {/* Agent 图标 */}
                  <div className="shrink-0 mt-0.5">
                    {isCompleted ? (
                      <CheckCircle2 className="w-4 h-4 text-green-600 dark:text-green-400" />
                    ) : isFailed ? (
                      <span className="w-4 h-4 flex items-center justify-center text-red-500 text-xs font-bold">!</span>
                    ) : (
                      <Loader2 className="w-4 h-4 text-blue-600 dark:text-blue-400 animate-spin" />
                    )}
                  </div>

                  {/* 内容 */}
                  <div className="flex-1 min-w-0">
                    {/* 标题行 */}
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-medium text-muted-foreground">
                        #{index + 1}
                      </span>
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium",
                          isCompleted
                            ? "bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300"
                            : isRunning
                            ? "bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300"
                            : "bg-muted text-muted-foreground"
                        )}
                      >
                        <IconComponent className="w-3 h-3" />
                        {step.agent}
                      </span>
                      <span className="text-xs font-medium text-foreground/80">
                        {step.step}
                      </span>
                      {isRunning && (
                        <span className="text-xs text-blue-500 animate-pulse">执行中</span>
                      )}
                    </div>

                    {/* 详细描述 */}
                    {step.detail && (
                      <p className="text-xs text-muted-foreground/80 mt-1.5 whitespace-pre-wrap leading-relaxed">
                        {step.detail}
                      </p>
                    )}

                    {/* 推理链 */}
                    {step.reasoning_chain && step.reasoning_chain.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {step.reasoning_chain.slice(0, 3).map((node, nodeIdx) => (
                          <div key={nodeIdx} className="flex items-start gap-1.5">
                            <span className="text-[10px] text-muted-foreground/50 mt-1">•</span>
                            <span className="text-[11px] text-muted-foreground/70">{node.content}</span>
                          </div>
                        ))}
                        {step.reasoning_chain.length > 3 && (
                          <span className="text-[10px] text-muted-foreground/50">
                            +{step.reasoning_chain.length - 3} 更多...
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* 显示阶段进度（如果没有详细步骤） */}
            {safeSteps.length === 0 && safeStates.map((state, index) => (
              <PhaseItem key={state.phase || index} state={state} index={index} />
            ))}
          </div>
        </ScrollArea>
      )}

      {compact && (
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {safeSteps.slice(-3).map((step, index) => {
            const isRunning = step.status === "running";
            const IconComponent = AGENT_ICONS[step.agent || ""] || Bot;
            return (
              <div
                key={`${step.agent}-${step.step}`}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors border",
                  isRunning
                    ? "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800"
                    : "bg-green-50 text-green-700 border-green-200 dark:bg-green-900/30 dark:text-green-300 dark:border-green-800"
                )}
              >
                {isRunning ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-3 h-3" />
                )}
                <IconComponent className="w-3 h-3" />
                <span>{step.agent}</span>
                <span className="opacity-60">{step.step}</span>
              </div>
            );
          })}
          {safeSteps.length === 0 && safeStates.map((state) => (
            <div
              key={state.phase}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors border",
                state.completed
                  ? "bg-green-50 text-green-700 border-green-200 dark:bg-green-900/30 dark:text-green-300 dark:border-green-800"
                  : "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800 animate-pulse"
              )}
            >
              {state.completed ? (
                <CheckCircle2 className="w-3 h-3" />
              ) : (
                <Loader2 className="w-3 h-3 animate-spin" />
              )}
              <span>{state.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface PhaseItemProps {
  state: ProcessingState;
  index: number;
}

function PhaseItem({ state, index }: PhaseItemProps) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 p-3 rounded-xl border transition-all",
        state.completed
          ? "bg-green-50/70 border-green-200/50 dark:bg-green-950/20 dark:border-green-800/30"
          : "bg-blue-50/70 border-blue-200/50 dark:bg-blue-950/20 dark:border-blue-800/30 animate-pulse"
      )}
    >
      <div className="shrink-0 mt-0.5">
        {state.completed ? (
          <CheckCircle2 className="w-4 h-4 text-green-600 dark:text-green-400" />
        ) : (
          <Loader2 className="w-4 h-4 text-blue-600 dark:text-blue-400 animate-spin" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            #{index + 1}
          </span>
          {state.agentName && (
            <span className="px-1.5 py-0.5 text-[10px] rounded bg-primary/10 text-primary font-medium">
              {state.agentName}
            </span>
          )}
        </div>
        <p className="text-sm mt-0.5 whitespace-pre-wrap leading-relaxed">{state.message}</p>
      </div>
    </div>
  );
}

// 骨架屏组件
export function AgentThinkingSkeleton() {
  return (
    <div className="flex flex-col gap-3 p-4 animate-pulse">
      <div className="flex items-center gap-2">
        <Bot className="w-4 h-4 text-muted-foreground" />
        <span className="text-sm text-muted-foreground">AI 正在思考...</span>
      </div>

      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="flex items-start gap-3 p-2 rounded-lg bg-blue-50 dark:bg-blue-950/20"
          >
            <Circle className="w-4 h-4 text-blue-400 animate-pulse" />
            <div className="flex-1">
              <div className="h-3 w-16 bg-blue-200 dark:bg-blue-800 rounded mb-2" />
              <div className="h-4 w-32 bg-blue-100 dark:bg-blue-900/50 rounded" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
