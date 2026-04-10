"use client";

import React, { useMemo, useCallback } from "react";
import { cn } from "@/lib/utils";
import {
  Bot,
  Sparkles,
  MapPin,
  Wallet,
  CloudSun,
  Cloud,
  CalendarDays,
  Lightbulb,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Cpu,
  ArrowRight,
  GitBranch,
  Zap,
  Users,
  Network,
  ChevronDown,
  ChevronRight,
  Wrench,
  Brain,
  Globe,
  Terminal,
  Search,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { DAGVisualization } from "./dag-visualization";
import { ExecutionTimeline } from "./execution-timeline";
import { RAGRetrievalDisplay, RAGRetrievalBadge } from "./rag-retrieval";
import { UserLearningDisplay, LearningBadge } from "./user-learning";
import type { ProcessingState, AgentResult, ThinkingStep, ReasoningNode, ToolCall as ToolCallType, AgentMetrics, APICall, RAGQuery, LearningStep } from "@/types";
import { getReasoningIcon } from "@/types";

interface ChainOfThoughtProps {
  states: ProcessingState[];
  agentResults?: AgentResult[];
  thinkingSteps?: ThinkingStep[];
  agentMetrics?: Record<string, AgentMetrics>;
}

// Agent 图标映射
const agentIcons: Record<string, React.ElementType> = {
  系统: Sparkles,
  编排器: Cpu,
  planner: Lightbulb,
  Planner: Lightbulb,
  attraction: MapPin,
  Attraction: MapPin,
  budget: Wallet,
  Budget: Wallet,
  weather: CloudSun,
  Weather: CloudSun,
  itinerary: CalendarDays,
  Itinerary: CalendarDays,
  review: CheckCircle2,
  Review: CheckCircle2,
  default: Bot,
};

// Agent 颜色映射
const agentColors: Record<string, string> = {
  系统: "bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-900/30 dark:text-purple-300 dark:border-purple-800",
  编排器: "bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800",
  Planner: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800",
  Attraction: "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800",
  Weather: "bg-sky-100 text-sky-700 border-sky-200 dark:bg-sky-900/30 dark:text-sky-300 dark:border-sky-800",
  Itinerary: "bg-orange-100 text-orange-700 border-orange-200 dark:bg-orange-900/30 dark:text-orange-300 dark:border-orange-800",
  Budget: "bg-rose-100 text-rose-700 border-rose-200 dark:bg-rose-900/30 dark:text-rose-300 dark:border-rose-800",
  Review: "bg-teal-100 text-teal-700 border-teal-200 dark:bg-teal-900/30 dark:text-teal-300 dark:border-teal-800",
};

// 状态图标
const StatusIcon = ({ status }: { status: string }) => {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />;
    case "failed":
      return <XCircle className="w-3.5 h-3.5 text-red-500" />;
    case "running":
      return <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />;
    default:
      return <Clock className="w-3.5 h-3.5 text-gray-400" />;
  }
};

// 推理节点渲染
const ReasoningNodeItem = ({ node, depth = 0 }: { node: ReasoningNode; depth?: number }) => {
  const [expanded, setExpanded] = React.useState(depth === 0);

  return (
    <div className={cn("flex flex-col", depth > 0 && "ml-4")}>
      <div
        className="flex items-center gap-1.5 py-0.5 cursor-pointer hover:bg-muted/50 rounded"
        onClick={() => node.children && node.children.length > 0 && setExpanded(!expanded)}
      >
        {node.children && node.children.length > 0 ? (
          expanded ? (
            <ChevronDown className="w-3 h-3 text-muted-foreground" />
          ) : (
            <ChevronRight className="w-3 h-3 text-muted-foreground" />
          )
        ) : (
          <span className="w-3" />
        )}
        <span className="text-sm">{getReasoningIcon(node.reasoning_type)}</span>
        <span className="text-xs text-muted-foreground flex-1 whitespace-pre-wrap">
          {node.content}
        </span>
      </div>
      {expanded && node.children && node.children.length > 0 && (
        <div className="border-l border-muted ml-1.5">
          {node.children.map((child, idx) => (
            <ReasoningNodeItem key={idx} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

// 工具调用渲染 - 增强版
const ToolCallItem = ({ call, showDetails = false }: { call: ToolCallType; showDetails?: boolean }) => {
  const statusColors = {
    pending: "text-gray-400",
    running: "text-blue-500",
    completed: "text-green-500",
    failed: "text-red-500",
  };

  const statusBgColors = {
    pending: "bg-gray-100 dark:bg-gray-800",
    running: "bg-blue-100 dark:bg-blue-900/30",
    completed: "bg-green-100 dark:bg-green-900/30",
    failed: "bg-red-100 dark:bg-red-900/30",
  };

  const statusBorderColors = {
    pending: "border-gray-200 dark:border-gray-700",
    running: "border-blue-200 dark:border-blue-800",
    completed: "border-green-200 dark:border-green-800",
    failed: "border-red-200 dark:border-red-800",
  };

  return (
    <div className={cn(
      "p-2 rounded-lg border transition-all",
      statusBgColors[call.status] || statusBgColors.pending,
      statusBorderColors[call.status] || statusBorderColors.pending
    )}>
      <div className="flex items-center gap-2">
        <Wrench className={cn("w-3.5 h-3.5", statusColors[call.status] || statusColors.pending)} />
        <span className="font-medium text-sm">{call.tool_name}</span>
        {call.duration_ms !== undefined && (
          <span className="text-xs text-muted-foreground ml-auto">
            {call.duration_ms.toFixed(0)}ms
          </span>
        )}
        {call.status === "completed" && (
          <CheckCircle2 className="w-3 h-3 text-green-500" />
        )}
        {call.status === "failed" && (
          <XCircle className="w-3 h-3 text-red-500" />
        )}
      </div>
      {/* 参数详情 */}
      {showDetails && call.arguments && Object.keys(call.arguments).length > 0 && (
        <div className="mt-2 pl-5 text-xs">
          <div className="text-muted-foreground mb-1">参数:</div>
          <div className="bg-black/5 dark:bg-white/5 p-1.5 rounded font-mono overflow-x-auto">
            {Object.entries(call.arguments).map(([key, value]) => (
              <div key={key}>
                <span className="text-blue-600 dark:text-blue-400">{key}</span>
                <span className="text-muted-foreground mx-1">=</span>
                <span className="text-green-600 dark:text-green-400">
                  {typeof value === 'string' ? `"${value}"` : JSON.stringify(value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {/* 错误信息 */}
      {showDetails && call.error && (
        <div className="mt-2 pl-5 text-xs text-red-500">
          错误: {call.error}
        </div>
      )}
    </div>
  );
};

// 外部 API 调用渲染 - 新增
const APICallItem = ({ call }: { call: APICall }) => {
  const statusColors = {
    pending: "text-gray-400",
    running: "text-blue-500",
    completed: "text-green-500",
    failed: "text-red-500",
  };

  const statusBgColors = {
    pending: "bg-gray-100 dark:bg-gray-800",
    running: "bg-blue-100 dark:bg-blue-900/30",
    completed: "bg-emerald-100 dark:bg-emerald-900/30",
    failed: "bg-red-100 dark:bg-red-900/30",
  };

  const statusBorderColors = {
    pending: "border-gray-200 dark:border-gray-700",
    running: "border-blue-200 dark:border-blue-800",
    completed: "border-emerald-200 dark:border-emerald-800",
    failed: "border-red-200 dark:border-red-800",
  };

  return (
    <div className={cn(
      "p-2 rounded-lg border transition-all",
      statusBgColors[call.status] || statusBgColors.pending,
      statusBorderColors[call.status] || statusBorderColors.pending
    )}>
      <div className="flex items-center gap-2">
        <Globe className={cn("w-3.5 h-3.5", statusColors[call.status] || statusColors.pending)} />
        <span className="font-medium text-sm">{call.service}</span>
        {call.duration_ms !== undefined && (
          <span className="text-xs text-muted-foreground ml-auto">
            {call.duration_ms.toFixed(0)}ms
          </span>
        )}
        {call.http_status && (
          <span className={cn(
            "text-[10px] px-1 py-0.5 rounded",
            call.http_status < 300 ? "bg-green-200 text-green-700 dark:bg-green-900/50 dark:text-green-400" :
            call.http_status < 400 ? "bg-yellow-200 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-400" :
            "bg-red-200 text-red-700 dark:bg-red-900/50 dark:text-red-400"
          )}>
            {call.http_status}
          </span>
        )}
      </div>
      {/* 端点信息 */}
      <div className="mt-1 pl-5 text-xs text-muted-foreground font-mono">
        {call.endpoint}
      </div>
      {/* 参数详情 */}
      {call.params && Object.keys(call.params).length > 0 && (
        <div className="mt-2 pl-5 text-xs">
          <div className="bg-black/5 dark:bg-white/5 p-1.5 rounded font-mono overflow-x-auto">
            {Object.entries(call.params).slice(0, 3).map(([key, value]) => (
              <div key={key}>
                <span className="text-purple-600 dark:text-purple-400">{key}</span>
                <span className="text-muted-foreground mx-1">:</span>
                <span className="text-orange-600 dark:text-orange-400">
                  {typeof value === 'string' ? value : JSON.stringify(value)}
                </span>
              </div>
            ))}
            {Object.keys(call.params).length > 3 && (
              <div className="text-muted-foreground">
                ... +{Object.keys(call.params).length - 3} more
              </div>
            )}
          </div>
        </div>
      )}
      {/* 错误信息 */}
      {call.error && (
        <div className="mt-2 pl-5 text-xs text-red-500 flex items-center gap-1">
          <XCircle className="w-3 h-3" />
          {call.error}
        </div>
      )}
    </div>
  );
};

// 详细思考步骤卡片 - 增强版
const ThinkingStepCard = ({ step }: { step: ThinkingStep }) => {
  const [expanded, setExpanded] = React.useState(false);
  const hasDetails = step.reasoning_chain?.length || step.tool_calls?.length || step.api_calls?.length;

  return (
    <div className="space-y-2 p-2 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors">
      {/* 标题行 */}
      <div className="flex items-center gap-2">
        <StatusIcon status={step.status} />
        <span className="text-sm font-medium">{step.step}</span>
        {/* 工具/API调用/RAG/学习数量提示 */}
        {(step.tool_calls?.length || step.api_calls?.length || step.rag_queries?.length || step.learning_steps?.length) > 0 && !expanded && (
          <div className="flex items-center gap-1 ml-2">
            {step.tool_calls && step.tool_calls.length > 0 && (
              <span className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-orange-100 text-orange-700 text-[10px] dark:bg-orange-900/30 dark:text-orange-400">
                <Wrench className="w-2.5 h-2.5" />
                {step.tool_calls.length}
              </span>
            )}
            {step.api_calls && step.api_calls.length > 0 && (
              <span className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-emerald-100 text-emerald-700 text-[10px] dark:bg-emerald-900/30 dark:text-emerald-400">
                <Globe className="w-2.5 h-2.5" />
                {step.api_calls.length}
              </span>
            )}
            {step.rag_queries && step.rag_queries.length > 0 && (
              <span className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-blue-100 text-blue-700 text-[10px] dark:bg-blue-900/30 dark:text-blue-400">
                <Search className="w-2.5 h-2.5" />
                {step.rag_queries.length}
              </span>
            )}
            {step.learning_steps && step.learning_steps.length > 0 && (
              <span className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-purple-100 text-purple-700 text-[10px] dark:bg-purple-900/30 dark:text-purple-400">
                <Brain className="w-2.5 h-2.5" />
                {step.learning_steps.length}
              </span>
            )}
          </div>
        )}
        {hasDetails && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="ml-auto p-1 hover:bg-muted rounded"
          >
            {expanded ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
          </button>
        )}
      </div>

      {/* 详情内容 */}
      {expanded ? (
        <div className="pl-4 space-y-3">
          {/* 推理链 */}
          {step.reasoning_chain && step.reasoning_chain.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Brain className="w-3 h-3" />
                <span>推理过程</span>
              </div>
              {step.reasoning_chain.map((node, idx) => (
                <ReasoningNodeItem key={idx} node={node} />
              ))}
            </div>
          )}

          {/* 工具调用 */}
          {step.tool_calls && step.tool_calls.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Wrench className="w-3 h-3" />
                <span>工具调用</span>
                <span className="ml-1 px-1 py-0.5 rounded bg-orange-100 text-orange-700 text-[10px] dark:bg-orange-900/30 dark:text-orange-400">
                  {step.tool_calls.length}
                </span>
              </div>
              <div className="space-y-1">
                {step.tool_calls.map((call, idx) => (
                  <ToolCallItem key={idx} call={call} showDetails />
                ))}
              </div>
            </div>
          )}

          {/* 外部 API 调用 */}
          {step.api_calls && step.api_calls.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Globe className="w-3 h-3" />
                <span>外部 API 调用</span>
                <span className="ml-1 px-1 py-0.5 rounded bg-emerald-100 text-emerald-700 text-[10px] dark:bg-emerald-900/30 dark:text-emerald-400">
                  {step.api_calls.length}
                </span>
              </div>
              <div className="space-y-1">
                {step.api_calls.map((call, idx) => (
                  <APICallItem key={idx} call={call} />
                ))}
              </div>
            </div>
          )}

          {/* RAG 检索 */}
          {step.rag_queries && step.rag_queries.length > 0 && (
            <RAGRetrievalDisplay ragQueries={step.rag_queries} />
          )}

          {/* 用户学习 */}
          {step.learning_steps && step.learning_steps.length > 0 && (
            <UserLearningDisplay learningSteps={step.learning_steps} />
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground line-clamp-2 pl-4">
          {step.detail}
        </p>
      )}
    </div>
  );
};

// Agent 执行阶段信息
interface AgentExecution {
  agent: string;
  startTime?: string;
  endTime?: string;
  status: "pending" | "running" | "completed" | "failed";
  steps: ThinkingStep[];
}

// 并行执行组
interface ParallelGroup {
  id: string;
  agents: AgentExecution[];
  status: "pending" | "running" | "completed";
  startTime?: string;
  endTime?: string;
}

export function ChainOfThought({
  states,
  agentResults = [],
  thinkingSteps = [],
  agentMetrics = {},
}: ChainOfThoughtProps) {
  // 按 Agent 分组思考步骤
  const groupedSteps = useMemo(() => {
    const groups: Record<string, ThinkingStep[]> = {};
    for (const step of thinkingSteps) {
      const agent = step.agent || "未知";
      if (!groups[agent]) {
        groups[agent] = [];
      }
      groups[agent].push(step);
    }
    return groups;
  }, [thinkingSteps]);

  // 分析并行执行模式
  const parallelGroups = useMemo((): ParallelGroup[] => {
    const groups: ParallelGroup[] = [];
    const agentOrder: string[] = [];

    // 按时间顺序排列 Agent
    for (const step of thinkingSteps) {
      const agent = step.agent;
      if (!agentOrder.includes(agent)) {
        agentOrder.push(agent);
      }
    }

    // 检测并行执行
    const completedAgents = agentOrder.filter((agent) => {
      const steps = groupedSteps[agent] || [];
      return steps.length > 0 && steps.every((s) => s.status === "completed");
    });

    // 第一批：意图解析（系统/编排器）
    if (agentOrder.includes("系统") || agentOrder.includes("编排器")) {
      groups.push({
        id: "phase-1-intent",
        agents: [
          {
            agent: "系统",
            status: completedAgents.includes("系统")
              ? "completed"
              : groupedSteps["系统"]?.some((s) => s.status === "running")
              ? "running"
              : "pending",
            steps: groupedSteps["系统"] || [],
          },
          {
            agent: "编排器",
            status: completedAgents.includes("编排器")
              ? "completed"
              : groupedSteps["编排器"]?.some((s) => s.status === "running")
              ? "running"
              : "pending",
            steps: groupedSteps["编排器"] || [],
          },
        ],
        status:
          completedAgents.includes("系统") && completedAgents.includes("编排器")
            ? "completed"
            : "running",
      });
    }

    // 第二批：数据收集（并行）
    const parallelAgents = ["Attraction", "Weather"];
    const hasParallel = parallelAgents.some((a) => agentOrder.includes(a));
    if (hasParallel) {
      const parallelGroup: ParallelGroup = {
        id: "phase-2-parallel",
        agents: [],
        status: "running",
      };

      for (const agent of parallelAgents) {
        if (agentOrder.includes(agent)) {
          const steps = groupedSteps[agent] || [];
          parallelGroup.agents.push({
            agent,
            status: completedAgents.includes(agent)
              ? "completed"
              : steps.some((s) => s.status === "running")
              ? "running"
              : "pending",
            steps,
          });
        }
      }

      if (parallelGroup.agents.length > 0) {
        const allCompleted = parallelGroup.agents.every((a) => a.status === "completed");
        parallelGroup.status = allCompleted
          ? "completed"
          : parallelGroup.agents.some((a) => a.status === "running")
          ? "running"
          : "pending";
        groups.push(parallelGroup);
      }
    }

    // 第三批：规划（顺序）
    const planningAgents = ["Itinerary", "Budget", "Planner"];
    for (const agent of planningAgents) {
      if (agentOrder.includes(agent)) {
        const steps = groupedSteps[agent] || [];
        groups.push({
          id: `phase-${agent}`,
          agents: [
            {
              agent,
              status: completedAgents.includes(agent)
                ? "completed"
                : steps.some((s) => s.status === "running")
                ? "running"
                : "pending",
              steps,
            },
          ],
          status: completedAgents.includes(agent)
            ? "completed"
            : steps.some((s) => s.status === "running")
            ? "running"
            : "pending",
        });
      }
    }

    return groups;
  }, [groupedSteps, thinkingSteps, agentResults]);

  // 获取 Agent 图标
  const getAgentIcon = (agentName: string) => {
    return agentIcons[agentName] || agentIcons.default;
  };

  // 获取 Agent 颜色
  const getAgentColor = (agentName: string) => {
    return (
      agentColors[agentName] ||
      "bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700"
    );
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 mb-4">
        <Cpu className="w-5 h-5 text-primary" />
        <h2 className="font-semibold">Agent 协作过程</h2>
      </div>

      <ScrollArea className="flex-1 -mr-4 pr-4">
        <div className="space-y-6">
          {/* Agent 执行指标 */}
          {Object.keys(agentMetrics).length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <Network className="w-4 h-4" />
                Agent 执行指标
              </h3>
              <div className="grid grid-cols-1 gap-2">
                {Object.entries(agentMetrics).map(([name, metrics]) => (
                  <div
                    key={name}
                    className={cn(
                      "p-3 rounded-lg border",
                      metrics.status === "completed"
                        ? "bg-green-50/50 border-green-200 dark:bg-green-950/20"
                        : "bg-muted/30 border-muted"
                    )}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-sm">{name}</span>
                      <StatusIcon status={metrics.status} />
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div>
                        <span className="text-muted-foreground">耗时</span>
                        <p className="font-medium">{metrics.execution_time_ms.toFixed(0)}ms</p>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Tokens</span>
                        <p className="font-medium">{metrics.tokens_used}</p>
                      </div>
                      <div>
                        <span className="text-muted-foreground">工具调用</span>
                        <p className="font-medium">{metrics.tool_calls_count}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <Separator />
            </div>
          )}

          {/* 执行流程可视化 */}
          {parallelGroups.length > 0 && (
            <div className="space-y-4">
              <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <GitBranch className="w-4 h-4" />
                执行流程
              </h3>

              <div className="space-y-3">
                {parallelGroups.map((group, groupIndex) => {
                  const isParallel = group.agents.length > 1;
                  const groupStatus = group.status;

                  return (
                    <div key={group.id} className="space-y-2">
                      {/* 执行阶段标签 */}
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">
                          {groupIndex + 1}.
                        </span>
                        {isParallel && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 text-[10px] font-medium dark:bg-purple-900/30 dark:text-purple-300">
                            <Zap className="w-3 h-3" />
                            并行
                          </span>
                        )}
                        {!isParallel && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 text-[10px] font-medium dark:bg-blue-900/30 dark:text-blue-300">
                            <ArrowRight className="w-3 h-3" />
                            顺序
                          </span>
                        )}
                      </div>

                      {/* Agent 卡片 */}
                      <div
                        className={cn(
                          "rounded-lg border p-3 transition-all",
                          groupStatus === "completed"
                            ? "bg-green-50/50 border-green-200 dark:bg-green-950/20 dark:border-green-900"
                            : groupStatus === "running"
                            ? "bg-blue-50/50 border-blue-200 dark:bg-blue-950/20 dark:border-blue-900"
                            : "bg-muted/30 border-muted"
                        )}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          {group.agents.map((agentExec) => {
                            const AgentIcon = getAgentIcon(agentExec.agent);
                            const colorClass = getAgentColor(agentExec.agent);
                            const lastStep = agentExec.steps[agentExec.steps.length - 1];
                            const metrics = agentMetrics[agentExec.agent];

                            return (
                              <div key={agentExec.agent} className="flex items-center gap-2">
                                {isParallel && groupIndex > 0 && (
                                  <GitBranch className="w-3 h-3 text-purple-400" />
                                )}
                                <div
                                  className={cn(
                                    "flex items-center gap-1.5 px-2 py-1 rounded-md border text-xs font-medium",
                                    colorClass,
                                    agentExec.status === "running" && "ring-2 ring-blue-400 ring-offset-1"
                                  )}
                                >
                                  {agentExec.status === "running" && (
                                    <Loader2 className="w-3 h-3 animate-spin" />
                                  )}
                                  {agentExec.status === "completed" && (
                                    <CheckCircle2 className="w-3 h-3" />
                                  )}
                                  {agentExec.status === "pending" && (
                                    <Clock className="w-3 h-3" />
                                  )}
                                  <AgentIcon className="w-3 h-3" />
                                  {agentExec.agent}
                                </div>
                                {lastStep && (
                                  <span className="text-[10px] text-muted-foreground max-w-[100px] truncate">
                                    {lastStep.step}
                                  </span>
                                )}
                                {metrics && metrics.status === "completed" && (
                                  <span className="text-[10px] text-muted-foreground">
                                    {metrics.execution_time_ms.toFixed(0)}ms
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      {/* 连接线 */}
                      {groupIndex < parallelGroups.length - 1 && (
                        <div className="flex justify-center">
                          <ArrowRight className="w-4 h-4 text-muted-foreground/50 rotate-90" />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              <Separator />
            </div>
          )}

          {/* 实时思考过程 - 增强版 */}
          {Object.keys(groupedSteps).length > 0 && (
            <div className="space-y-4">
              <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <Sparkles className="w-4 h-4" />
                详细思考过程
              </h3>

              {/* Agent 分组展示 */}
              {Object.entries(groupedSteps).map(([agent, steps]) => {
                const AgentIcon = getAgentIcon(agent);
                const colorClass = getAgentColor(agent);
                const lastStep = steps[steps.length - 1];
                const isRunning = lastStep?.status === "running";
                const metrics = agentMetrics[agent];

                return (
                  <div key={agent} className="space-y-3">
                    {/* Agent 标题 */}
                    <div className="flex items-center gap-2">
                      <div
                        className={cn(
                          "px-2 py-1 rounded-md border text-xs font-medium flex items-center gap-1.5",
                          colorClass
                        )}
                      >
                        <AgentIcon className="w-3 h-3" />
                        {agent}
                      </div>
                      {isRunning && (
                        <span className="text-xs text-blue-500 animate-pulse flex items-center gap-1">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          执行中...
                        </span>
                      )}
                      {metrics && (
                        <span className="text-xs text-muted-foreground ml-auto">
                          {metrics.tokens_used} tokens
                        </span>
                      )}
                    </div>

                    {/* 步骤卡片 */}
                    <div className="space-y-2 pl-2">
                      {steps.map((step, index) => (
                        <ThinkingStepCard key={index} step={step} />
                      ))}
                    </div>
                  </div>
                );
              })}

              <Separator />
            </div>
          )}

          {/* 处理阶段 */}
          {states.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <ArrowRight className="w-4 h-4" />
                处理阶段
              </h3>
              <div className="space-y-2">
                {states.map((state, index) => (
                  <div
                    key={index}
                    className={cn(
                      "flex items-start gap-3 p-3 rounded-lg border transition-all",
                      state.completed
                        ? "bg-green-50/50 border-green-200 dark:bg-green-950/20 dark:border-green-900"
                        : "bg-blue-50/50 border-blue-200 dark:bg-blue-950/20 dark:border-blue-900"
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
                      {state.agentName && (
                        <span className="px-1.5 py-0.5 text-[10px] rounded bg-primary/10 text-primary font-medium">
                          {state.agentName}
                        </span>
                      )}
                      <p className="text-sm mt-0.5">{state.message}</p>
                    </div>
                  </div>
                ))}
              </div>

              <Separator />
            </div>
          )}

          {/* DAG 依赖关系可视化 */}
          {thinkingSteps.length > 0 && (
            <div className="py-2">
              <DAGVisualization thinkingSteps={thinkingSteps} />
              <Separator className="mt-6" />
            </div>
          )}

          {/* 统计信息 */}
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Users className="w-4 h-4" />
              执行统计
            </h3>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="p-3 rounded-lg bg-muted/50">
                <p className="text-muted-foreground text-xs">完成进度</p>
                <p className="text-lg font-semibold">
                  {thinkingSteps.filter((s) => s.status === "completed").length}/
                  {thinkingSteps.length}
                </p>
              </div>
              <div className="p-3 rounded-lg bg-muted/50">
                <p className="text-muted-foreground text-xs">活跃 Agent</p>
                <p className="text-lg font-semibold">{Object.keys(groupedSteps).length}</p>
              </div>
              <div className="p-3 rounded-lg bg-purple-50/50 dark:bg-purple-950/20 col-span-2">
                <p className="text-muted-foreground text-xs">执行策略</p>
                <p className="text-sm font-medium flex items-center gap-1">
                  <Zap className="w-3 h-3 text-purple-500" />
                  Attraction + Weather 并行执行
                </p>
              </div>
            </div>
          </div>

          {/* 空状态 */}
          {thinkingSteps.length === 0 && states.length === 0 && agentResults.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Cpu className="w-12 h-12 text-muted-foreground/30 mb-4" />
              <p className="text-sm text-muted-foreground">
                开始对话后，这里将实时展示 Agent 的协作过程
              </p>
              <div className="flex items-center gap-1 mt-4 text-xs text-muted-foreground">
                <span className="px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">
                  <Zap className="w-3 h-3 inline" /> 并行
                </span>
                <ArrowRight className="w-3 h-3" />
                <span className="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">
                  <ArrowRight className="w-3 h-3 inline" /> 顺序
                </span>
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

// 骨架屏
export function ChainOfThoughtSkeleton() {
  return (
    <div className="flex flex-col h-full animate-pulse">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-5 h-5 rounded bg-muted" />
        <div className="h-5 w-24 bg-muted rounded" />
      </div>

      <div className="space-y-6">
        {/* 执行流程骨架 */}
        <div className="space-y-3">
          <div className="h-4 w-16 bg-muted rounded" />
          {[1, 2].map((i) => (
            <div key={i} className="p-3 rounded-lg border">
              <div className="flex items-center gap-2">
                <div className="w-16 h-6 rounded bg-blue-100 dark:bg-blue-900/30" />
                <div className="w-16 h-6 rounded bg-green-100 dark:bg-green-900/30" />
              </div>
            </div>
          ))}
        </div>

        {/* Agent 分组骨架 */}
        {[1, 2, 3].map((i) => (
          <div key={i} className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="w-16 h-6 rounded bg-blue-100 dark:bg-blue-900/30" />
            </div>
            <div className="ml-4 space-y-2 border-l-2 border-muted pl-4">
              {[1, 2].map((j) => (
                <div key={j} className="flex items-start gap-2">
                  <div className="w-4 h-4 rounded-full bg-blue-200 dark:bg-blue-800" />
                  <div className="space-y-1">
                    <div className="h-3 w-20 bg-blue-100 dark:bg-blue-900/30 rounded" />
                    <div className="h-2 w-32 bg-blue-50 dark:bg-blue-900/10 rounded" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
