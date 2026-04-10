"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { User, Bot, Sparkles, HelpCircle, MessageSquare } from "lucide-react";
import type { DialogMode, EmotionType } from "@/types";

interface ModeIndicatorProps {
  mode: DialogMode;
  detectedEmotion?: EmotionType | null;
}

const modeConfig = {
  planning: {
    icon: Sparkles,
    label: "规划模式",
    color: "text-blue-600 bg-blue-50 dark:text-blue-400 dark:bg-blue-950",
  },
  qa: {
    icon: HelpCircle,
    label: "问答模式",
    color: "text-green-600 bg-green-50 dark:text-green-400 dark:bg-green-950",
  },
  chat: {
    icon: MessageSquare,
    label: "闲聊模式",
    color: "text-purple-600 bg-purple-50 dark:text-purple-400 dark:bg-purple-950",
  },
};

const emotionEmojis: Record<EmotionType, string> = {
  neutral: "",
  happy: "😊",
  excited: "🤩",
  frustrated: "😤",
  confused: "🤔",
  worried: "😟",
  satisfied: "😊",
};

export function ModeIndicator({ mode, detectedEmotion }: ModeIndicatorProps) {
  const config = modeConfig[mode] || modeConfig.planning;
  const Icon = config.icon;

  return (
    <div className="flex items-center gap-2">
      <div
        className={cn(
          "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors",
          config.color
        )}
      >
        <Icon className="w-3.5 h-3.5" />
        <span>{config.label}</span>
      </div>
      {detectedEmotion && detectedEmotion !== "neutral" && (
        <span className="text-base" title={`情绪: ${detectedEmotion}`}>
          {emotionEmojis[detectedEmotion]}
        </span>
      )}
    </div>
  );
}

interface AgentAvatarProps {
  agentName?: string;
  size?: "sm" | "md" | "lg";
}

const agentColors: Record<string, string> = {
  orchestrator: "bg-purple-500",
  planner: "bg-gradient-to-br from-blue-500 to-indigo-600",
  attraction: "bg-gradient-to-br from-green-500 to-emerald-600",
  itinerary: "bg-gradient-to-br from-orange-500 to-amber-500",
  budget: "bg-gradient-to-br from-yellow-500 to-orange-500",
  weather: "bg-gradient-to-br from-cyan-500 to-blue-500",
  review: "bg-gradient-to-br from-pink-500 to-rose-500",
  memory: "bg-gradient-to-br from-indigo-500 to-purple-500",
  default: "bg-gradient-to-br from-primary/80 to-primary",
};

const agentDisplayNames: Record<string, string> = {
  planner: "旅游规划助手",
  orchestrator: "行程管家",
  attraction: "景点推荐",
  itinerary: "行程规划",
  budget: "预算分析",
  weather: "天气助手",
  review: "质量审查",
  memory: "记忆助手",
};

export function AgentAvatar({ agentName, size = "md" }: AgentAvatarProps) {
  const sizeClasses = {
    sm: "w-6 h-6",
    md: "w-8 h-8",
    lg: "w-10 h-10",
  };

  const colorClass = agentName
    ? agentColors[agentName.toLowerCase()] || agentColors.default
    : agentColors.default;

  const iconClass = size === "sm" ? "w-3 h-3" : size === "lg" ? "w-5 h-5" : "w-4 h-4";

  return (
    <Avatar className={cn(sizeClasses[size])}>
      <AvatarFallback
        className={cn(
          colorClass,
          "text-white shadow-sm",
          size === "md" && "text-sm",
          size === "lg" && "text-base"
        )}
      >
        <Sparkles className={iconClass} />
      </AvatarFallback>
    </Avatar>
  );
}

/** 获取 Agent 展示名称（产品化映射） */
export function getAgentDisplayName(agentName?: string): string {
  if (!agentName) return "助手";
  return agentDisplayNames[agentName.toLowerCase()] || agentName;
}

interface UserAvatarProps {
  size?: "sm" | "md" | "lg";
}

export function UserAvatar({ size = "md" }: UserAvatarProps) {
  const sizeClasses = {
    sm: "w-6 h-6",
    md: "w-8 h-8",
    lg: "w-10 h-10",
  };

  return (
    <Avatar className={cn(sizeClasses[size])}>
      <AvatarFallback className="bg-muted">
        <User className="w-4 h-4" />
      </AvatarFallback>
    </Avatar>
  );
}
