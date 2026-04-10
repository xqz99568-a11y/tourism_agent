"use client";

import React from "react";
import { cn } from "@/lib/utils";
import {
  Brain,
  Lightbulb,
  Heart,
  Wallet,
  Clock,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  TrendingUp,
} from "lucide-react";
import type { LearningStep } from "@/types";

interface UserLearningDisplayProps {
  learningSteps: LearningStep[];
  className?: string;
}

// 类别图标映射
const categoryIcons: Record<LearningStep["category"], React.ElementType> = {
  preference: Lightbulb,
  behavior: Brain,
  budget: Wallet,
  timing: Clock,
};

// 类别颜色映射
const categoryColors: Record<LearningStep["category"], { bg: string; text: string }> = {
  preference: { bg: "bg-amber-100 dark:bg-amber-900/30", text: "text-amber-700 dark:text-amber-400" },
  behavior: { bg: "bg-purple-100 dark:bg-purple-900/30", text: "text-purple-700 dark:text-purple-400" },
  budget: { bg: "bg-green-100 dark:bg-green-900/30", text: "text-green-700 dark:text-green-400" },
  timing: { bg: "bg-sky-100 dark:bg-sky-900/30", text: "text-sky-700 dark:text-sky-400" },
};

// 类别名称映射
const categoryNames: Record<LearningStep["category"], string> = {
  preference: "偏好",
  behavior: "行为",
  budget: "预算",
  timing: "时机",
};

export function UserLearningDisplay({ learningSteps, className }: UserLearningDisplayProps) {
  if (!learningSteps || learningSteps.length === 0) {
    return null;
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <Brain className="w-3 h-3" />
        <span>用户画像学习</span>
        <span className="ml-1 px-1 py-0.5 rounded bg-purple-100 text-purple-700 text-[10px] dark:bg-purple-900/30 dark:text-purple-400">
          {learningSteps.length}
        </span>
      </div>

      <div className="space-y-2">
        {learningSteps.map((step, index) => (
          <LearningStepCard key={index} step={step} />
        ))}
      </div>
    </div>
  );
}

function LearningStepCard({ step }: { step: LearningStep }) {
  const [expanded, setExpanded] = React.useState(false);
  const CategoryIcon = categoryIcons[step.category] || Brain;
  const colors = categoryColors[step.category] || categoryColors.behavior;

  // 置信度颜色
  const confidenceColor = step.confidence >= 0.8 ? "text-green-500" :
                           step.confidence >= 0.6 ? "text-blue-500" :
                           "text-gray-500";

  return (
    <div className="border rounded-lg overflow-hidden bg-card">
      {/* 标题行 */}
      <div
        className="flex items-center gap-2 p-2 cursor-pointer hover:bg-muted/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="w-3 h-3 text-muted-foreground" />
        ) : (
          <ChevronRight className="w-3 h-3 text-muted-foreground" />
        )}
        <div className={cn("p-1 rounded", colors.bg)}>
          <CategoryIcon className={cn("w-3 h-3", colors.text)} />
        </div>
        <span className="text-xs font-medium flex-1 truncate">
          {step.user_action}
        </span>
        <span className={cn("px-1 py-0.5 rounded text-[10px]", colors.bg, colors.text)}>
          {categoryNames[step.category]}
        </span>
      </div>

      {/* 详情内容 */}
      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          {/* 系统学到的内容 */}
          <div className="space-y-1">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <TrendingUp className="w-3 h-3" />
              <span>系统学习到</span>
            </div>
            <div className="flex items-start gap-2 p-2 rounded bg-muted/30">
              <Lightbulb className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
              <p className="text-xs text-muted-foreground flex-1">
                {step.system_learned}
              </p>
            </div>
          </div>

          {/* 置信度 */}
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span>置信度</span>
              <span className={cn("font-medium", confidenceColor)}>
                {(step.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  step.confidence >= 0.8 ? "bg-green-500" :
                  step.confidence >= 0.6 ? "bg-blue-500" : "bg-gray-400"
                )}
                style={{ width: `${step.confidence * 100}%` }}
              />
            </div>
          </div>

          {/* 时间戳 */}
          {step.timestamp && (
            <div className="text-[10px] text-muted-foreground">
              {new Date(step.timestamp).toLocaleString()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// 简化版学习徽章
export function LearningBadge({ learningSteps }: { learningSteps: LearningStep[] }) {
  if (!learningSteps || learningSteps.length === 0) {
    return null;
  }

  return (
    <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 text-[10px] dark:bg-purple-900/30 dark:text-purple-400">
      <Brain className="w-3 h-3" />
      <span>学习 {learningSteps.length}</span>
    </div>
  );
}

// 学习统计摘要
export function LearningSummary({ learningSteps }: { learningSteps: LearningStep[] }) {
  if (!learningSteps || learningSteps.length === 0) {
    return null;
  }

  // 统计各类别
  const categoryCount = learningSteps.reduce((acc, step) => {
    acc[step.category] = (acc[step.category] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  // 计算平均置信度
  const avgConfidence = learningSteps.reduce((sum, step) => sum + step.confidence, 0) / learningSteps.length;

  return (
    <div className="flex items-center gap-3 text-xs">
      {/* 类别分布 */}
      <div className="flex items-center gap-1">
        {Object.entries(categoryCount).map(([category, count]) => {
          const CategoryIcon = categoryIcons[category as LearningStep["category"]] || Brain;
          const colors = categoryColors[category as LearningStep["category"]] || categoryColors.behavior;
          return (
            <div
              key={category}
              className={cn("flex items-center gap-0.5 px-1 py-0.5 rounded", colors.bg)}
              title={`${categoryNames[category as LearningStep["category"]]}: ${count}`}
            >
              <CategoryIcon className={cn("w-3 h-3", colors.text)} />
              <span className={colors.text}>{count}</span>
            </div>
          );
        })}
      </div>

      {/* 平均置信度 */}
      <div className="flex items-center gap-1 text-muted-foreground">
        <CheckCircle2 className="w-3 h-3" />
        <span>{(avgConfidence * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}
