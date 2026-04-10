"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useChatStore, useUIStore } from "@/stores/chat-store";
import { streamChat } from "@/lib/api-hooks";
import { MessageBubble } from "./message-bubble";
import { ChatInput, type ChatInputRef } from "./chat-input";
import { ModeIndicator } from "./chat-avatars";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { ChainOfThought } from "./chain-of-thought";
import { Bot, RefreshCw, PanelRight, Sparkles } from "lucide-react";
import type { ChatMessage, ProcessingState, ThinkingStep, AgentMetrics } from "@/types";

// 【本轮修复】per-turn stream 状态隔离
interface StreamState {
  abortController: AbortController;
  assistantMsgId: string;
  requestId: string;
}

// 阶段 -> ProcessingState
const PHASE_MESSAGES: Record<string, string> = {
  intent_parsing:        "🔍 正在分析您的意图...",
  task_planning:          "📋 正在制定执行计划...",
  parallel_execution:     "⚡ 正在并行执行各模块任务...",
  result_aggregation:    "📦 正在汇总各模块结果...",
  quality_review:         "✅ 正在执行质量审查...",
  response_synthesis:     "💬 正在生成最终响应...",
  agent_execution:        "🚀 正在执行 Agent 任务...",
  agent_step:             "🤖 Agent 处理中...",
  chat_mode:              "💬 正在回复...",
  qa_mode:                "🔎 正在查询答案...",
  mode_detection:         "🎯 正在检测对话模式...",
};

const defaultSuggestions = [
  "帮我规划一个北京3天游，预算3000元",
  "五一去杭州玩3天，想吃美食、看西湖，预算4000",
  "帮我做一个上海周末2天旅行计划，预算2000",
];

const CHAT_ERROR_MESSAGE = "抱歉，处理您的请求时出现了错误，请稍后重试。";

export function ChatPage() {
  const {
    sessionId,
    currentMode,
    detectedEmotion,
    messages,
    isProcessing,
    processingStates,
    thinkingSteps,
    suggestions,
    setSessionId,
    setCurrentMode,
    setDetectedEmotion,
    addMessage,
    patchMessage,
    setIsProcessing,
    setProcessingStates,
    setThinkingSteps,
    clearThinkingSteps,
    setSuggestions,
    reset,
  } = useChatStore();

  const { isChainOfThoughtOpen, toggleChainOfThought } = useUIStore();

  // 增强：Agent 指标状态
  const [agentMetrics, setAgentMetrics] = useState<Record<string, AgentMetrics>>({});

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<ChatInputRef>(null);

  // 【本轮修复】per-turn stream 状态隔离 ref
  const activeStreamRef = useRef<StreamState | null>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, processingStates]);

  // 【修复】页面刷新时清空状态，始终回到初始欢迎页
  useEffect(() => {
    // 清空本地存储的聊天记录
    localStorage.removeItem("tourism-chat-storage");
    // 重置状态
    reset();
  }, []);

  // 处理发送消息
  const handleSend = useCallback(async (input: string) => {
    if (!input) return;

    // 【本轮修复】同一时间只允许一个 active stream
    // 如果有活动流，先中止旧流，标记旧 assistant 消息为已中断
    if (activeStreamRef.current) {
      activeStreamRef.current.abortController.abort();
      // 标记旧 assistant 消息为已中断（保留已有内容）
      const oldMsgId = activeStreamRef.current.assistantMsgId;
      patchMessage(oldMsgId, { isInterrupted: true } as any);
      activeStreamRef.current = null;
    }

    // 清空之前的指标
    setAgentMetrics({});

    // 【本轮修复】为每个 turn 生成唯一的 requestId
    const requestId = crypto.randomUUID();

    // 【本轮修复】在 try 块内声明变量，避免重复声明
    let assistantMsgId: string;
    let currentRequestId: string;
    let currentAssistantMsgId: string;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: input,
      timestamp: new Date().toISOString(),
    };

    addMessage(userMessage);
    setIsProcessing(true);
    setProcessingStates([
      { phase: "analyzing", message: "正在分析目的地和您的需求...", completed: false },
    ]);
    setSuggestions([]);

    try {
      // 清空输入框
      inputRef.current?.clear();

      // 【本轮修复】为每个 turn 创建独立的 stream state
      const abortController = new AbortController();

      // 预建一条空的 assistant 气泡，后续增量更新
      assistantMsgId = crypto.randomUUID();
      const assistantMsg: ChatMessage = {
        id: assistantMsgId,
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        agentName: "planner",
      };
      addMessage(assistantMsg);

      // 保存当前 turn 的 stream state
      activeStreamRef.current = {
        abortController,
        assistantMsgId,
        requestId,
      };

      // 【本轮修复】在赋值后记录到外层变量
      currentRequestId = requestId;
      currentAssistantMsgId = assistantMsgId;

      // 流式处理（传递 abort signal）
      const eventGenerator = await streamChat({
        sessionId,
        message: input,
        stream: true,
      }, { signal: abortController.signal });

      let pendingStates: ProcessingState[] = [];
      let streamingContent = "";
      // 【本轮修复】使用外层已赋值的变量

      for await (const event of eventGenerator) {
        // 【本轮修复】忽略不属于当前 turn 的事件
        if (activeStreamRef.current?.requestId !== currentRequestId) {
          break;
        }

        const data = event.data as Record<string, unknown>;

        // ── agent_step / pipeline 阶段 ──────────────────────────────────
        if (event.type === "agent_step") {
          // 同步 thinking_steps
          if (data.thinking_steps && Array.isArray(data.thinking_steps)) {
            setThinkingSteps(data.thinking_steps as ThinkingStep[]);
          }

          // 更新 agent metrics
          if (data.agent_metrics) {
            setAgentMetrics(data.agent_metrics as Record<string, AgentMetrics>);
          }

          // 收集 pipeline 阶段 -> ProcessingState
          const phase = data.phase as string | undefined;
          if (phase) {
            const phaseMsg = PHASE_MESSAGES[phase] ?? (data.message as string) ?? phase;
            const isRunning = data.status === "running";
            const isDone = data.status === "completed";

            const idx = pendingStates.findIndex((s) => s.phase === phase);
            if (idx >= 0) {
              pendingStates = pendingStates.map((s, i) =>
                i === idx ? { ...s, completed: isDone } : s
              );
            } else if (isRunning) {
              pendingStates = [...pendingStates, { phase, message: phaseMsg, completed: false }];
            }
            setProcessingStates(pendingStates);
          }

          // agent 执行结果 -> metrics
          if (data.results && Array.isArray(data.results)) {
            const metrics: Record<string, AgentMetrics> = {};
            for (const r of data.results as { agent: string; success: boolean; execution_time_ms?: number }[]) {
              metrics[r.agent] = {
                agent_name: r.agent,
                execution_time_ms: r.execution_time_ms ?? 0,
                tokens_used: 0,
                tool_calls_count: 0,
                status: r.success ? "completed" : "pending",
              };
            }
            setAgentMetrics(metrics);
          }
        }

        // ── 模式 / 情感 / 建议 ───────────────────────────────────────────
        if (data.mode) setCurrentMode(data.mode as "planning" | "qa" | "chat");
        if (data.emotion) setDetectedEmotion(data.emotion as import("@/types").EmotionType);
        if (data.suggestions && Array.isArray(data.suggestions)) {
          setSuggestions(data.suggestions as string[]);
        }

        // ── 流式正文增量（边生成边显示）───────────────────────────────────
        if (event.type === "streaming") {
          if (data.content && typeof data.content === "string" && data.content.length > 0) {
            streamingContent += data.content as string;
            patchMessage(currentAssistantMsgId, { content: streamingContent });
          }
        }

        // ── final（仅此一次，真正结束）──────────────────────────────────
        if (event.type === "final") {
          const finalContent = data.content;
          if (typeof finalContent === "string" && finalContent.trim().length > 0) {
            streamingContent = finalContent;
            patchMessage(currentAssistantMsgId, { content: finalContent });
          }
          setProcessingStates([]);
          clearThinkingSteps();
          // 【本轮修复】流正常结束时清理 activeStreamRef
          if (activeStreamRef.current?.requestId === currentRequestId) {
            activeStreamRef.current = null;
          }
        }
      }
    } catch (error) {
      console.error("Chat error:", error);
      // 【本轮修复】安全兜底：有占位消息 id 就 patch；没有就追加一条失败消息
      if (currentAssistantMsgId) {
        patchMessage(currentAssistantMsgId, {
          content: CHAT_ERROR_MESSAGE,
        });
      } else {
        const failMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: CHAT_ERROR_MESSAGE,
          timestamp: new Date().toISOString(),
          agentName: "planner",
        };
        addMessage(failMsg);
      }
      setProcessingStates([
        { phase: "error", message: "处理失败，请重试", completed: true },
      ]);
    } finally {
      setProcessingStates([]);
      clearThinkingSteps();
      setIsProcessing(false);
      // 【本轮修复】确保 finally 块也清理 activeStreamRef
      if (activeStreamRef.current?.requestId === currentRequestId) {
        activeStreamRef.current = null;
      }
    }
  }, [
    sessionId,
    addMessage,
    patchMessage,
    setIsProcessing,
    setProcessingStates,
    clearThinkingSteps,
    setCurrentMode,
    setDetectedEmotion,
    setSuggestions,
    setAgentMetrics,
  ]);

  // 新建对话
  const handleNewChat = () => {
    const newSessionId = crypto.randomUUID();
    reset();
    setSessionId(newSessionId);
    setAgentMetrics({});
  };

  // 建议点击
  const handleSuggestionClick = (suggestion: string) => {
    handleSend(suggestion);
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary/10">
            <Sparkles className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="font-semibold text-lg">旅游规划助手</h1>
            <p className="text-xs text-muted-foreground">基于大模型的智能规划</p>
          </div>
          <ModeIndicator mode={currentMode} detectedEmotion={detectedEmotion} />
        </div>

        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={handleNewChat}>
            <RefreshCw className="w-4 h-4 mr-1.5" />
            新对话
          </Button>

          <Sheet open={isChainOfThoughtOpen} onOpenChange={toggleChainOfThought}>
            <SheetTrigger asChild>
              <div className="inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground h-10 w-10 relative">
                <PanelRight className="w-4 h-4" />
                {/* 显示活跃的思考步骤数量 */}
                {thinkingSteps.length > 0 && (
                  <span className="absolute -top-1 -right-1 w-4 h-4 bg-primary text-primary-foreground text-[10px] rounded-full flex items-center justify-center">
                    {thinkingSteps.length > 9 ? "9+" : thinkingSteps.length}
                  </span>
                )}
              </div>
            </SheetTrigger>
            <SheetContent side="right" className="w-[420px] sm:w-[480px]">
              <ChainOfThought
                states={processingStates}
                thinkingSteps={thinkingSteps}
                agentMetrics={agentMetrics}
              />
            </SheetContent>
          </Sheet>
        </div>
      </header>

      {/* Messages */}
      <ScrollArea ref={scrollRef} className="flex-1">
        <div className="max-w-3xl mx-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <EmptyState onSuggestionClick={handleSuggestionClick} />
          ) : (
            <>
              {messages.map((message, index) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  isStreaming={isProcessing && message.role === "assistant" && index === messages.length - 1}
                />
              ))}
            </>
          )}
        </div>
      </ScrollArea>

      {/* Suggestions */}
      {suggestions.length > 0 && !isProcessing && (
        <div className="px-4 pb-2">
          <div className="flex flex-wrap gap-2 justify-center">
            {suggestions.map((suggestion, i) => (
              <button
                key={i}
                onClick={() => handleSuggestionClick(suggestion)}
                className="px-3 py-1.5 text-sm bg-muted hover:bg-muted/80 rounded-full transition-colors text-muted-foreground"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="p-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="max-w-3xl mx-auto">
          <ChatInput
            ref={inputRef}
            onSend={handleSend}
            disabled={isProcessing}
            isLoading={isProcessing}
            placeholder="描述您的旅行需求..."
          />
        </div>
      </div>
    </div>
  );
}

// 空状态组件
interface EmptyStateProps {
  onSuggestionClick: (suggestion: string) => void;
}

function EmptyState({ onSuggestionClick }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center mb-6">
        <Bot className="w-10 h-10 text-primary" />
      </div>

      <h2 className="text-xl font-semibold mb-2">开始您的旅行规划</h2>
      <p className="text-muted-foreground mb-6 max-w-md">
        告诉我您想去哪里旅行、人数和时间，我来帮您制定完美的行程规划！
      </p>

      <div className="flex flex-wrap gap-2 justify-center">
        {defaultSuggestions.map((suggestion, i) => (
          <button
            key={i}
            onClick={() => onSuggestionClick(suggestion)}
            className="px-4 py-2 text-sm bg-muted hover:bg-muted/80 rounded-full transition-colors"
          >
            {suggestion}
          </button>
        ))}
      </div>

      {/* 特性列表 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-12 max-w-2xl">
        {[
          { icon: "🗺️", title: "智能规划", desc: "AI 驱动的个性化路线" },
          { icon: "💰", title: "预算分析", desc: "透明的花费预估" },
          { icon: "🍜", title: "美食推荐", desc: "当地特色美食指南" },
          { icon: "🌤️", title: "天气提醒", desc: "出行前的气象信息" },
        ].map((feature, i) => (
          <div
            key={i}
            className="flex flex-col items-center p-3 rounded-xl bg-muted/50 hover:bg-muted transition-colors"
          >
            <span className="text-2xl mb-2">{feature.icon}</span>
            <span className="text-sm font-medium">{feature.title}</span>
            <span className="text-xs text-muted-foreground">{feature.desc}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
