"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { CheckCircle2, Bot, Loader2 } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { AgentResult } from "@/types/chat";

interface ProcessingState {
  phase: string;
  message: string;
  completed: boolean;
}

interface ChainOfThoughtProps {
  states: ProcessingState[];
  agentResults?: AgentResult[];
}

const PHASE_LABELS: Record<string, string> = {
  analyzing: "意图分析",
  planning: "任务规划",
  intent_parsing: "意图解析",
  task_planning: "任务规划",
  parallel_execution: "并行执行",
  result_aggregation: "结果聚合",
  quality_review: "质量审查",
  response_synthesis: "响应生成",
  searching: "搜索景点",
  calculating: "计算预算",
  generating: "生成行程",
  reviewing: "审查结果",
};

export function ChainOfThought({ states, agentResults = [] }: ChainOfThoughtProps) {
  return (
    <div className="flex flex-col h-full">
      <h3 className="text-lg font-semibold mb-4">思考过程</h3>

      <ScrollArea className="flex-1 -mr-4 pr-4">
        <div className="space-y-4">
          {/* Phase list */}
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-muted-foreground">处理阶段</h4>
            {states.length === 0 ? (
              <p className="text-sm text-muted-foreground">等待处理...</p>
            ) : (
              <div className="space-y-2">
                {states.map((state, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <div className="mt-0.5">
                      {state.completed ? (
                        <CheckCircle2 className="w-4 h-4 text-green-500" />
                      ) : (
                        <Loader2 className="w-4 h-4 animate-spin text-primary" />
                      )}
                    </div>
                    <div>
                      <p className="text-sm font-medium">
                        {PHASE_LABELS[state.phase] || state.phase}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {state.message}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <Separator />

          {/* Agent results */}
          {agentResults.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-muted-foreground">Agent 执行结果</h4>
              <div className="space-y-3">
                {agentResults.map((result, i) => (
                  <div
                    key={i}
                    className={cn(
                      "p-3 rounded-lg border",
                      result.success ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200"
                    )}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Bot className="w-4 h-4" />
                        <span className="text-sm font-medium">{result.agentName}</span>
                      </div>
                      <span
                        className={cn(
                          "text-xs px-2 py-0.5 rounded",
                          result.success
                            ? "bg-green-100 text-green-700"
                            : "bg-red-100 text-red-700"
                        )}
                      >
                        {result.success ? "成功" : "失败"}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mb-2">
                      执行时间: {result.executionTimeMs.toFixed(0)}ms
                    </p>
                    {result.toolsUsed.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {result.toolsUsed.map((tool, j) => (
                          <span
                            key={j}
                            className="text-xs px-1.5 py-0.5 rounded bg-secondary"
                          >
                            {tool}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <Separator />

          {/* Statistics */}
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-muted-foreground">统计信息</h4>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="p-2 rounded bg-muted">
                <p className="text-muted-foreground">已完成阶段</p>
                <p className="text-lg font-semibold">
                  {states.filter((s) => s.completed).length} / {states.length}
                </p>
              </div>
              <div className="p-2 rounded bg-muted">
                <p className="text-muted-foreground">执行 Agent</p>
                <p className="text-lg font-semibold">{agentResults.length}</p>
              </div>
            </div>
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}
