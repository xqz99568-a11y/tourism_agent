"use client";

import React, { useMemo } from "react";
import { format } from "date-fns";
import { zhCN } from "date-fns/locale";
import { cn } from "@/lib/utils";
import { UserAvatar, AgentAvatar, getAgentDisplayName } from "./chat-avatars";
import type { ChatMessage } from "@/types";
import { MarkdownRenderer } from "./markdown-renderer";

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

export function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isEmptyAssistant = !isUser && !message.content?.trim();

  const formattedTime = useMemo(() => {
    try {
      return format(new Date(message.timestamp), "HH:mm", { locale: zhCN });
    } catch {
      return "";
    }
  }, [message.timestamp]);

  return (
    <div
      className={cn(
        "flex gap-3 group animate-in fade-in slide-in-from-bottom-2 duration-300",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      {isUser ? <UserAvatar /> : <AgentAvatar agentName={message.agentName} />}

      <div
        className={cn(
          "flex flex-col gap-1 max-w-[85%] sm:max-w-[75%]",
          isUser ? "items-end" : "items-start"
        )}
      >
        {!isUser && message.agentName && (
          <span className="text-xs font-medium text-muted-foreground/70 px-1">
            {getAgentDisplayName(message.agentName)}
          </span>
        )}

        <div
          className={cn(
            "relative rounded-2xl px-4 py-2.5 text-sm leading-relaxed transition-all",
            isUser
              ? "bg-primary text-primary-foreground rounded-tr-sm"
              : "bg-muted/80 backdrop-blur rounded-tl-sm border border-border/50"
          )}
        >
          {isEmptyAssistant ? (
            <div className="flex items-center gap-2 text-muted-foreground min-h-[1.25rem]">
              <span className="inline-flex gap-1">
                <span className="size-2 rounded-full bg-primary/60 animate-bounce [animation-delay:-0.2s]" />
                <span className="size-2 rounded-full bg-primary/60 animate-bounce [animation-delay:-0.1s]" />
                <span className="size-2 rounded-full bg-primary/60 animate-bounce" />
              </span>
              <span className="text-sm">正在撰写回复...</span>
            </div>
          ) : isStreaming && !isUser ? (
            <div className="whitespace-pre-wrap break-words">
              {message.content}
            </div>
          ) : (
            <MarkdownRenderer content={message.content} isUser={isUser} />
          )}
        </div>

        <span className="text-[10px] text-muted-foreground/60 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {formattedTime}
        </span>
      </div>
    </div>
  );
}
