"use client";

import React, { useMemo } from "react";
import { cn } from "@/lib/utils";
import {
  Bot,
  MapPin,
  Wallet,
  CloudSun,
  CalendarDays,
  Lightbulb,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  GitBranch,
  Zap,
} from "lucide-react";
import type { AgentMetrics } from "@/types";

// Agent 图标映射
const agentIcons: Record<string, React.ElementType> = {
  系统: Bot,
  编排器: Bot,
  Planner: Lightbulb,
  Attraction: MapPin,
  Weather: CloudSun,
  Itinerary: CalendarDays,
  Budget: Wallet,
  Review: CheckCircle2,
};

// Agent 颜色映射
const agentColors: Record<string, { bg: string; border: string; progress: string }> = {
  系统: { bg: "bg-purple-100", border: "border-purple-300", progress: "bg-purple-500" },
  编排器: { bg: "bg-blue-100", border: "border-blue-300", progress: "bg-blue-500" },
  Planner: { bg: "bg-amber-100", border: "border-amber-300", progress: "bg-amber-500" },
  Attraction: { bg: "bg-emerald-100", border: "border-emerald-300", progress: "bg-emerald-500" },
  Weather: { bg: "bg-sky-100", border: "border-sky-300", progress: "bg-sky-500" },
  Itinerary: { bg: "bg-orange-100", border: "border-orange-300", progress: "bg-orange-500" },
  Budget: { bg: "bg-rose-100", border: "border-rose-300", progress: "bg-rose-500" },
  Review: { bg: "bg-teal-100", border: "border-teal-300", progress: "bg-teal-500" },
};

// 执行时间线事件
interface TimelineEvent {
  agent: string;
  phase: string;
  startMs: number;
  durationMs: number;
  status: "pending" | "running" | "completed" | "failed";
  isParallel: boolean;
}

interface ExecutionTimelineProps {
  agentMetrics?: Record<string, AgentMetrics>;
  totalDurationMs?: number;
  className?: string;
}

export function ExecutionTimeline({
  agentMetrics = {},
  totalDurationMs,
  className,
}: ExecutionTimelineProps) {
  // 根据指标计算时间线
  const timeline = useMemo(() => {
    const events: TimelineEvent[] = [];
    let currentTime = 0;

    // 定义执行顺序和并行关系
    const executionOrder = [
      { agent: "系统", phase: "意图解析", isParallel: false },
      { agent: "编排器", phase: "任务规划", isParallel: false },
      // 并行执行组
      { agent: "Attraction", phase: "景点搜索", isParallel: true, group: 1 },
      { agent: "Weather", phase: "天气查询", isParallel: true, group: 1 },
      // 顺序执行
      { agent: "Itinerary", phase: "行程规划", isParallel: false },
      { agent: "Budget", phase: "预算分析", isParallel: false },
      { agent: "Planner", phase: "综合整理", isParallel: false },
    ];

    // 第一批并行组的最大时长
    let parallelGroup1MaxDuration = 0;

    // 计算每个 Agent 的执行时长
    for (const item of executionOrder) {
      const metrics = agentMetrics[item.agent];
      const durationMs = metrics?.execution_time_ms || 200; // 默认200ms

      if (item.isParallel) {
        // 并行执行组
        if (item.group === 1) {
          // 第一个并行组
          if (durationMs > parallelGroup1MaxDuration) {
            parallelGroup1MaxDuration = durationMs;
          }
          events.push({
            agent: item.agent,
            phase: item.phase,
            startMs: currentTime,
            durationMs,
            status: metrics?.status || "pending",
            isParallel: true,
          });
        }
      } else if (item.agent === "Itinerary") {
        // 第一个顺序执行，等待并行组完成
        currentTime += parallelGroup1MaxDuration;
        events.push({
          agent: item.agent,
          phase: item.phase,
          startMs: currentTime,
          durationMs,
          status: metrics?.status || "pending",
          isParallel: false,
        });
        currentTime += durationMs;
      } else if (item.agent === "Budget") {
        events.push({
          agent: item.agent,
          phase: item.phase,
          startMs: currentTime,
          durationMs,
          status: metrics?.status || "pending",
          isParallel: false,
        });
        currentTime += durationMs;
      } else if (item.agent === "Planner") {
        events.push({
          agent: item.agent,
          phase: item.phase,
          startMs: currentTime,
          durationMs,
          status: metrics?.status || "pending",
          isParallel: false,
        });
        currentTime += durationMs;
      } else {
        events.push({
          agent: item.agent,
          phase: item.phase,
          startMs: currentTime,
          durationMs,
          status: metrics?.status || "pending",
          isParallel: false,
        });
        currentTime += durationMs;
      }
    }

    return {
      events,
      totalDuration: totalDurationMs || currentTime,
    };
  }, [agentMetrics, totalDurationMs]);

  const getAgentIcon = (agent: string) => agentIcons[agent] || Bot;
  const getAgentColor = (agent: string) =>
    agentColors[agent] || { bg: "bg-gray-100", border: "border-gray-300", progress: "bg-gray-500" };

  const StatusIcon = ({ status }: { status: string }) => {
    switch (status) {
      case "completed":
        return <CheckCircle2 className="w-3 h-3 text-green-500" />;
      case "failed":
        return <XCircle className="w-3 h-3 text-red-500" />;
      case "running":
        return <Loader2 className="w-3 h-3 text-blue-500 animate-spin" />;
      default:
        return <Clock className="w-3 h-3 text-gray-400" />;
    }
  };

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
          <GitBranch className="w-4 h-4" />
          执行时间线
        </h4>
        <span className="text-xs text-muted-foreground">
          总耗时: {timeline.totalDuration.toFixed(0)}ms
        </span>
      </div>

      {/* 图例 */}
      <div className="flex items-center gap-4 text-xs">
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-sm bg-purple-200" />
          <span className="text-muted-foreground">顺序</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-sm bg-emerald-200" />
          <span className="text-muted-foreground">并行</span>
        </div>
      </div>

      {/* 时间线甘特图 */}
      <div className="relative">
        {/* 时间轴 */}
        <div className="flex items-center mb-1 text-[10px] text-muted-foreground">
          <div className="w-20 shrink-0">Agent</div>
          <div className="flex-1 relative h-4">
            {/* 时间刻度 */}
            {[0, 25, 50, 75, 100].map((percent) => (
              <div
                key={percent}
                className="absolute text-center"
                style={{ left: `${percent}%` }}
              >
                {(timeline.totalDuration * percent / 100).toFixed(0)}ms
              </div>
            ))}
          </div>
          <div className="w-12 text-right shrink-0">时长</div>
        </div>

        {/* 执行条 */}
        <div className="space-y-1">
          {timeline.events.map((event, index) => {
            const Icon = getAgentIcon(event.agent);
            const colors = getAgentColor(event.agent);
            const widthPercent = (event.durationMs / timeline.totalDuration) * 100;
            const leftPercent = (event.startMs / timeline.totalDuration) * 100;
            const isLastParallel =
              event.isParallel &&
              index < timeline.events.length - 1 &&
              timeline.events[index + 1]?.isParallel;
            const isFirstParallel =
              event.isParallel &&
              index > 0 &&
              timeline.events[index - 1]?.isParallel;

            return (
              <div key={event.agent} className="flex items-center">
                {/* Agent 标签 */}
                <div className="w-20 shrink-0 flex items-center gap-1">
                  {event.isParallel && (
                    <GitBranch className="w-3 h-3 text-emerald-500" />
                  )}
                  <Icon className="w-3.5 h-3.5" />
                  <span className="text-xs truncate">{event.agent}</span>
                </div>

                {/* 时间条区域 */}
                <div className="flex-1 relative h-6">
                  {/* 背景网格 */}
                  <div className="absolute inset-0 flex">
                    {[0, 25, 50, 75, 100].map((percent) => (
                      <div
                        key={percent}
                        className="flex-1 border-l border-gray-200 dark:border-gray-700 first:border-l-0"
                      />
                    ))}
                  </div>

                  {/* 执行条 */}
                  <div
                    className={cn(
                      "absolute top-1 h-4 rounded-sm transition-all",
                      colors.bg,
                      colors.border,
                      "border",
                      event.status === "running" && "ring-2 ring-blue-400",
                      event.status === "completed" && colors.progress,
                      event.status === "failed" && "bg-red-200 dark:bg-red-900/30"
                    )}
                    style={{
                      left: `${leftPercent}%`,
                      width: `${Math.max(widthPercent, 5)}%`,
                      minWidth: "20px",
                    }}
                  >
                    {/* 运行中动画 */}
                    {event.status === "running" && (
                      <div
                        className={cn(
                          "absolute inset-0 bg-blue-400/50 rounded-sm animate-pulse",
                          colors.progress
                        )}
                        style={{ width: "100%" }}
                      />
                    )}
                  </div>

                  {/* 并行标记 */}
                  {event.isParallel && !isFirstParallel && (
                    <div
                      className="absolute top-1/2 -translate-y-1/2 w-0.5 bg-emerald-400"
                      style={{
                        left: `${leftPercent - 2}%`,
                        height: "16px",
                      }}
                    />
                  )}
                </div>

                {/* 时长 */}
                <div className="w-12 shrink-0 text-right text-xs text-muted-foreground flex items-center justify-end gap-1">
                  <StatusIcon status={event.status} />
                  <span>{event.durationMs.toFixed(0)}ms</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* 并行组标注 */}
        <div className="mt-2 pl-4 flex items-center gap-2">
          {timeline.events.some((e) => e.isParallel) && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 text-[10px] dark:bg-emerald-900/30 dark:text-emerald-400">
              <Zap className="w-3 h-3" />
              并行执行组
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// 简化版时间线（用于小空间展示）
export function ExecutionTimelineCompact({
  agentMetrics = {},
  className,
}: ExecutionTimelineProps) {
  const getAgentColor = (agent: string) =>
    agentColors[agent]?.progress || "bg-gray-500";

  const totalTime = useMemo(() => {
    return Object.values(agentMetrics).reduce(
      (sum, m) => sum + (m.execution_time_ms || 0),
      0
    );
  }, [agentMetrics]);

  return (
    <div className={cn("flex items-center gap-1", className)}>
      {Object.entries(agentMetrics).map(([name, metrics]) => {
        const widthPercent =
          totalTime > 0
            ? ((metrics.execution_time_ms || 0) / totalTime) * 100
            : 0;
        const color = getAgentColor(name);

        return (
          <div
            key={name}
            className={cn(
              "h-4 rounded-sm transition-all",
              color,
              metrics.status === "running" && "animate-pulse"
            )}
            style={{ width: `${Math.max(widthPercent, 2)}%` }}
            title={`${name}: ${metrics.execution_time_ms?.toFixed(0)}ms`}
          />
        );
      })}
    </div>
  );
}
