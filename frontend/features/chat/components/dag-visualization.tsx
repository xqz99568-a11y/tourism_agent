"use client";

import React, { useMemo } from "react";
import { cn } from "@/lib/utils";
import {
  Bot,
  Sparkles,
  MapPin,
  Wallet,
  CloudSun,
  CalendarDays,
  Lightbulb,
  CheckCircle2,
  Clock,
  Loader2,
  Cpu,
  ArrowRight,
  GitBranch,
} from "lucide-react";
import type { ThinkingStep } from "@/types";

interface DAGVisualizationProps {
  thinkingSteps?: ThinkingStep[];
}

// Agent 元数据
const agentMeta: Record<string, {
  icon: React.ElementType;
  color: string;
  borderColor: string;
  bgColor: string;
  label: string;
}> = {
  "系统": {
    icon: Sparkles,
    color: "text-purple-700 dark:text-purple-300",
    borderColor: "border-purple-300 dark:border-purple-700",
    bgColor: "bg-purple-50 dark:bg-purple-950/30",
    label: "系统"
  },
  "编排器": {
    icon: Cpu,
    color: "text-blue-700 dark:text-blue-300",
    borderColor: "border-blue-300 dark:border-blue-700",
    bgColor: "bg-blue-50 dark:bg-blue-950/30",
    label: "编排器"
  },
  "Planner": {
    icon: Lightbulb,
    color: "text-amber-700 dark:text-amber-300",
    borderColor: "border-amber-300 dark:border-amber-700",
    bgColor: "bg-amber-50 dark:bg-amber-950/30",
    label: "Planner"
  },
  "Attraction": {
    icon: MapPin,
    color: "text-emerald-700 dark:text-emerald-300",
    borderColor: "border-emerald-300 dark:border-emerald-700",
    bgColor: "bg-emerald-50 dark:bg-emerald-950/30",
    label: "景点"
  },
  "Weather": {
    icon: CloudSun,
    color: "text-sky-700 dark:text-sky-300",
    borderColor: "border-sky-300 dark:border-sky-700",
    bgColor: "bg-sky-50 dark:bg-sky-950/30",
    label: "天气"
  },
  "Itinerary": {
    icon: CalendarDays,
    color: "text-orange-700 dark:text-orange-300",
    borderColor: "border-orange-300 dark:border-orange-700",
    bgColor: "bg-orange-50 dark:bg-orange-950/30",
    label: "行程"
  },
  "Budget": {
    icon: Wallet,
    color: "text-rose-700 dark:text-rose-300",
    borderColor: "border-rose-300 dark:border-rose-700",
    bgColor: "bg-rose-50 dark:bg-rose-950/30",
    label: "预算"
  },
};

// 默认 Agent 元数据
const defaultMeta = {
  icon: Bot,
  color: "text-gray-700 dark:text-gray-300",
  borderColor: "border-gray-300 dark:border-gray-700",
  bgColor: "bg-gray-50 dark:bg-gray-900/30",
  label: "未知"
};

// DAG 节点
interface DAGNode {
  id: string;
  agent: string;
  meta: typeof defaultMeta;
  status: "pending" | "running" | "completed" | "failed";
  step?: string;
}

// DAG 边
interface DAGEdge {
  from: string;
  to: string;
  type: "parallel" | "sequential";
}

// 预定义的 Agent 依赖关系
const AGENT_DEPENDENCIES: Record<string, string[]> = {
  "Attraction": [],
  "Weather": [],
  "Itinerary": ["Attraction", "Weather"],
  "Budget": [],
  "Planner": ["Attraction", "Weather", "Itinerary", "Budget"],
};

// 并行组
const PARALLEL_GROUPS = [
  ["Attraction", "Weather"],
];

export function DAGVisualization({ thinkingSteps = [] }: DAGVisualizationProps) {
  // 分析思考步骤获取 Agent 状态
  const agentStatus = useMemo(() => {
    const status: Record<string, "pending" | "running" | "completed" | "failed"> = {};
    const agentSteps: Record<string, ThinkingStep[]> = {};

    for (const step of thinkingSteps) {
      const agent = step.agent || "未知";
      if (!agentSteps[agent]) {
        agentSteps[agent] = [];
      }
      agentSteps[agent].push(step);
    }

    for (const [agent, steps] of Object.entries(agentSteps)) {
      if (steps.some(s => s.status === "failed")) {
        status[agent] = "failed";
      } else if (steps.some(s => s.status === "running")) {
        status[agent] = "running";
      } else if (steps.every(s => s.status === "completed")) {
        status[agent] = "completed";
      } else {
        status[agent] = "pending";
      }
    }

    return status;
  }, [thinkingSteps]);

  // 构建 DAG 节点
  const nodes = useMemo((): DAGNode[] => {
    const agents = ["系统", "编排器", "Attraction", "Weather", "Itinerary", "Budget", "Planner"];
    return agents.map(agent => {
      const meta = agentMeta[agent] || defaultMeta;
      const status = agentStatus[agent] || "pending";
      const steps = thinkingSteps.filter(s => s.agent === agent);
      const currentStep = steps.length > 0 
        ? steps[steps.length - 1].step 
        : undefined;

      return {
        id: agent,
        agent,
        meta,
        status,
        step: currentStep,
      };
    });
  }, [agentStatus, thinkingSteps]);

  // 构建 DAG 边
  const edges = useMemo((): DAGEdge[] => {
    const edgeList: DAGEdge[] = [];

    // 从属关系到边
    for (const [agent, deps] of Object.entries(AGENT_DEPENDENCIES)) {
      if (deps.length === 0) continue;

      // 检查是否是并行依赖
      const isParallel = PARALLEL_GROUPS.some(group => 
        group.includes(agent) && deps.every(d => group.includes(d))
      );

      for (const dep of deps) {
        edgeList.push({
          from: dep,
          to: agent,
          type: isParallel ? "parallel" : "sequential",
        });
      }
    }

    return edgeList;
  }, []);

  // 判断节点是否在并行组中
  const isInParallelGroup = (agent: string) => {
    return PARALLEL_GROUPS.some(group => group.includes(agent));
  };

  // 获取并行组的节点
  const getParallelGroupNodes = () => {
    return PARALLEL_GROUPS.map((group, index) => ({
      id: `parallel-${index}`,
      agents: group,
      nodes: group.map(agent => nodes.find(n => n.id === agent)).filter(Boolean) as DAGNode[],
    }));
  };

  // 渲染节点状态图标
  const renderStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />;
      case "running":
        return <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />;
      case "failed":
        return <Clock className="w-3.5 h-3.5 text-red-500" />;
      default:
        return <Clock className="w-3.5 h-3.5 text-gray-400" />;
    }
  };

  // 渲染单个节点
  const renderNode = (node: DAGNode, showConnector: boolean = false) => {
    const Icon = node.meta.icon;

    return (
      <div key={node.id} className="flex flex-col items-center gap-1">
        {showConnector && (
          <div className="w-0.5 h-4 bg-muted-foreground/30" />
        )}
        <div
          className={cn(
            "flex flex-col items-center gap-1 px-3 py-2 rounded-lg border-2 transition-all min-w-[100px]",
            node.meta.borderColor,
            node.meta.bgColor,
            node.status === "running" && "ring-2 ring-blue-400 ring-offset-2",
            node.status === "completed" && "opacity-80"
          )}
        >
          <div className={cn("flex items-center gap-1.5", node.meta.color)}>
            {renderStatusIcon(node.status)}
            <Icon className="w-4 h-4" />
            <span className="text-xs font-medium">{node.meta.label}</span>
          </div>
          {node.step && (
            <span className="text-[10px] text-muted-foreground max-w-[80px] truncate">
              {node.step}
            </span>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* 标题 */}
      <div className="flex items-center gap-2">
        <GitBranch className="w-4 h-4 text-muted-foreground" />
        <h4 className="text-sm font-medium text-muted-foreground">Agent 依赖关系图</h4>
      </div>

      {/* DAG 可视化 */}
      <div className="space-y-4">
        {/* 第一层：系统/编排器 */}
        <div className="flex items-center justify-center gap-4">
          {renderNode(nodes.find(n => n.id === "系统")!)}
          <ArrowRight className="w-4 h-4 text-muted-foreground/50" />
          {renderNode(nodes.find(n => n.id === "编排器")!)}
        </div>

        {/* 连接线 */}
        <div className="flex justify-center">
          <div className="w-0.5 h-6 bg-muted-foreground/30" />
        </div>

        {/* 第二层：并行执行组 */}
        <div className="flex items-center justify-center gap-8">
          {/* 并行标记 */}
          <div className="absolute -ml-8 mt-2">
            <span className="text-[10px] text-purple-500 bg-purple-100 px-1.5 py-0.5 rounded dark:bg-purple-900/30">
              并行
            </span>
          </div>

          <div className="flex items-center gap-4">
            {/* 并行节点 */}
            <div className="relative">
              {/* 并行框 */}
              <div className="absolute inset-0 -m-2 border-2 border-dashed border-purple-300 rounded-lg dark:border-purple-700/50 bg-purple-50/30 dark:bg-purple-900/10" />
              <div className="relative flex items-center gap-4 p-2">
                {renderNode(nodes.find(n => n.id === "Attraction")!)}
                <div className="text-muted-foreground">|</div>
                {renderNode(nodes.find(n => n.id === "Weather")!)}
              </div>
            </div>
          </div>
        </div>

        {/* 连接线 */}
        <div className="flex justify-center">
          <div className="w-0.5 h-6 bg-muted-foreground/30" />
        </div>

        {/* 第三层：顺序执行 */}
        <div className="flex items-center justify-center gap-4 flex-wrap">
          {renderNode(nodes.find(n => n.id === "Itinerary")!)}
          <ArrowRight className="w-4 h-4 text-muted-foreground/50" />
          {renderNode(nodes.find(n => n.id === "Budget")!)}
        </div>

        {/* 连接线 */}
        <div className="flex justify-center">
          <div className="w-0.5 h-6 bg-muted-foreground/30" />
        </div>

        {/* 第四层：Planner */}
        <div className="flex items-center justify-center">
          {renderNode(nodes.find(n => n.id === "Planner")!)}
        </div>
      </div>

      {/* 图例 */}
      <div className="flex items-center justify-center gap-4 text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <CheckCircle2 className="w-3 h-3 text-green-500" />
          <span>已完成</span>
        </div>
        <div className="flex items-center gap-1">
          <Loader2 className="w-3 h-3 text-blue-500" />
          <span>执行中</span>
        </div>
        <div className="flex items-center gap-1">
          <Clock className="w-3 h-3 text-gray-400" />
          <span>等待中</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 border-2 border-dashed border-purple-300 rounded" />
          <span>并行执行</span>
        </div>
      </div>
    </div>
  );
}
