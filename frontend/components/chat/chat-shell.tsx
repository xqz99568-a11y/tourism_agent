"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import type { ChatMessage, AgentResult } from "@/types/chat";
import { streamChat, sendChat } from "@/lib/api";
import { ChatInput } from "./chat-input";
import { MessageBubble } from "./message-bubble";
import { AgentThinking } from "./agent-thinking";
import { ChainOfThought } from "./chain-of-thought";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Bot, PanelRight, RefreshCw, Sparkles, HelpCircle, MessageSquare } from "lucide-react";

type DialogMode = "planning" | "qa" | "chat";

interface ChatShellProps {
  sessionId: string;
  initialMessages?: ChatMessage[];
  onSessionChange?: (sessionId: string) => void;
}

interface ProcessingState {
  phase: string;
  message: string;
  completed: boolean;
}

// 模式指示器组件
function ModeIndicator({
  mode,
  detectedEmotion
}: {
  mode: DialogMode;
  detectedEmotion?: string;
}) {
  const modeConfig = {
    planning: {
      icon: Sparkles,
      label: "规划模式",
      color: "text-blue-500 bg-blue-50",
    },
    qa: {
      icon: HelpCircle,
      label: "问答模式",
      color: "text-green-500 bg-green-50",
    },
    chat: {
      icon: MessageSquare,
      label: "闲聊模式",
      color: "text-purple-500 bg-purple-50",
    },
  };

  const config = modeConfig[mode];
  const Icon = config.icon;

  return (
    <div className="flex items-center gap-2">
      <div className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs ${config.color}`}>
        <Icon className="w-3 h-3" />
        <span>{config.label}</span>
      </div>
      {detectedEmotion && detectedEmotion !== "neutral" && (
        <div className="text-xs text-muted-foreground">
          {detectedEmotion === "happy" && "😊"}
          {detectedEmotion === "excited" && "🤩"}
          {detectedEmotion === "frustrated" && "😤"}
          {detectedEmotion === "confused" && "🤔"}
          {detectedEmotion === "worried" && "😟"}
          {detectedEmotion === "satisfied" && "😊"}
        </div>
      )}
    </div>
  );
}

export function ChatShell({
  sessionId,
  initialMessages = [],
  onSessionChange,
}: ChatShellProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingStates, setProcessingStates] = useState<ProcessingState[]>([]);
  const [agentResults, setAgentResults] = useState<AgentResult[]>([]);
  const [showChainOfThought, setShowChainOfThought] = useState(false);
  const [currentMode, setCurrentMode] = useState<DialogMode>("planning");
  const [detectedEmotion, setDetectedEmotion] = useState<string | undefined>();
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollTop + 1000;
    }
  }, [messages, processingStates]);

  // 处理发送消息
  const handleSend = useCallback(async () => {
    if (!input.trim() || isProcessing) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsProcessing(true);
    setProcessingStates([{ phase: "analyzing", message: "正在分析您的需求...", completed: false }]);

    try {
      // 流式处理
      await new Promise<void>((resolve) => {
        streamChat(
          {
            sessionId,
            message: userMessage.content,
            stream: true,
          },
          (event) => {
            if (event.type === "message") {
              const data = event.data;

              // 更新模式信息
              if (data.mode) {
                setCurrentMode(data.mode);
              }
              if (data.emotion) {
                setDetectedEmotion(data.emotion);
              }
              if (data.suggestions) {
                setSuggestions(data.suggestions);
              }

              // 更新处理状态
              if (data.phase) {
                setProcessingStates((prev) =>
                  prev.map((s, i) =>
                    i === prev.length - 1
                      ? { ...s, phase: data.phase, message: data.message || s.message, completed: data.status === "completed" }
                      : s
                  )
                );
              }

              // 添加新的处理阶段
              setProcessingStates((prev) => {
                if (data.status === "running" && data.message && !prevStatesInclude(prev, data.phase)) {
                  return [
                    ...prev,
                    { phase: data.phase, message: data.message, completed: false },
                  ];
                }
                return prev;
              });
            }

            if (event.type === "final") {
              // 添加 AI 响应
              const aiMessage: ChatMessage = {
                id: crypto.randomUUID(),
                role: "assistant",
                content: event.data.content,
                timestamp: new Date().toISOString(),
                agentName: "planner",
              };

              setMessages((prev) => [...prev, aiMessage]);
              setProcessingStates([]);
              resolve();
            }
          }
        );
      });
    } catch (error) {
      console.error("Chat error:", error);
      setProcessingStates([{ phase: "error", message: "处理失败，请重试", completed: true }]);
    } finally {
      setIsProcessing(false);
    }
  }, [input, isProcessing, sessionId]);

  // 检查是否已有该阶段
  const prevStatesInclude = (states: ProcessingState[], phase: string) => {
    return states.some((s) => s.phase === phase);
  };

  // 处理按键
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 处理建议点击
  const handleSuggestionClick = (suggestion: string) => {
    setInput(suggestion);
    inputRef.current?.focus();
  };

  // 开始新对话
  const handleNewChat = () => {
    const newSessionId = crypto.randomUUID();
    setMessages([]);
    setProcessingStates([]);
    setCurrentMode("planning");
    setDetectedEmotion(undefined);
    setSuggestions([]);
    onSessionChange?.(newSessionId);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-3">
          <Bot className="w-6 h-6 text-primary" />
          <span className="font-semibold">旅游规划助手</span>
          <ModeIndicator mode={currentMode} detectedEmotion={detectedEmotion} />
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={handleNewChat}>
            <RefreshCw className="w-4 h-4 mr-2" />
            新对话
          </Button>
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="ghost" size="sm">
                <PanelRight className="w-4 h-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-[400px]">
              <ChainOfThought
                states={processingStates}
                agentResults={agentResults}
              />
            </SheetContent>
          </Sheet>
        </div>
      </div>

      {/* Messages */}
      <ScrollArea ref={scrollRef} className="flex-1 p-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground">
            <Bot className="w-16 h-16 mb-4 opacity-50" />
            <h3 className="text-lg font-medium mb-2">开始您的旅行规划</h3>
            <p className="text-sm max-w-md">
              告诉我您想去哪里旅行，我来帮您制定完美的行程规划！
            </p>
            <div className="flex flex-wrap gap-2 mt-4 justify-center">
              {[
                "帮我规划一个北京3日游",
                "推荐一些杭州的美食",
                "这周天气怎么样？",
              ].map((suggestion, i) => (
                <button
                  key={i}
                  onClick={() => handleSuggestionClick(suggestion)}
                  className="px-3 py-1.5 text-sm bg-muted hover:bg-muted/80 rounded-full transition-colors"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {processingStates.length > 0 && (
              <AgentThinking states={processingStates} />
            )}
          </div>
        )}
      </ScrollArea>

      {/* Suggestions */}
      {suggestions.length > 0 && !isProcessing && (
        <div className="px-4 pb-2">
          <div className="flex flex-wrap gap-2">
            {suggestions.map((suggestion, i) => (
              <button
                key={i}
                onClick={() => handleSuggestionClick(suggestion)}
                className="px-3 py-1.5 text-xs bg-muted hover:bg-muted/80 rounded-full transition-colors text-muted-foreground"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="p-4 border-t">
        <ChatInput
          ref={inputRef}
          value={input}
          onChange={setInput}
          onSend={handleSend}
          onKeyDown={handleKeyDown}
          disabled={isProcessing}
          placeholder="描述您的旅行需求..."
        />
      </div>
    </div>
  );
}
