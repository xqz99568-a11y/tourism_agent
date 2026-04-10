"use client";

import React, { forwardRef, useImperativeHandle, useRef, useEffect, useState, useCallback } from "react";
import { Send, Image, Mic, MicOff, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  isLoading?: boolean;
  placeholder?: string;
}

export interface ChatInputRef {
  clear: () => void;
  focus: () => void;
}

export const ChatInput = forwardRef<ChatInputRef, ChatInputProps>(
  (
    {
      onSend,
      disabled,
      isLoading,
      placeholder = "描述您的旅行需求...",
    },
    ref
  ) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [value, setValue] = useState("");
    const [isRecording, setIsRecording] = useState(false);
    const [recognition, setRecognition] = useState<SpeechRecognition | null>(null);
    const [selectedImage, setSelectedImage] = useState<string | null>(null);

    useImperativeHandle(ref, () => ({
      clear: () => setValue(""),
      focus: () => textareaRef.current?.focus(),
    }));

    // 自动调整高度
    useEffect(() => {
      const textarea = textareaRef.current;
      if (textarea) {
        textarea.style.height = "auto";
        textarea.style.height = `${Math.min(textarea.scrollHeight, 150)}px`;
      }
    }, [value]);

    // 初始化语音识别
    useEffect(() => {
      if (typeof window !== "undefined") {
        const SpeechRecognitionAPI =
          (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

        if (SpeechRecognitionAPI) {
          const recognition = new SpeechRecognitionAPI();
          recognition.continuous = false;
          recognition.interimResults = true;
          recognition.lang = "zh-CN";

          recognition.onresult = (event: any) => {
            let transcript = "";
            for (let i = event.resultIndex; i < event.results.length; i++) {
              transcript += event.results[i][0].transcript;
            }
            setValue(transcript);
          };

          recognition.onerror = (event: any) => {
            console.error("Speech recognition error:", event.error);
            setIsRecording(false);
          };

          recognition.onend = () => {
            setIsRecording(false);
          };

          setRecognition(recognition);
        }
      }
    }, []);

    // 处理图片选择
    const handleImageSelect = useCallback(
      (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) {
          const reader = new FileReader();
          reader.onload = (e) => {
            const imageData = e.target?.result as string;
            setSelectedImage(imageData);
          };
          reader.readAsDataURL(file);
        }
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
      },
      []
    );

    // 移除选中的图片
    const handleRemoveImage = () => {
      setSelectedImage(null);
    };

    // 切换语音输入
    const toggleVoiceInput = () => {
      if (!recognition) {
        alert("您的浏览器不支持语音输入");
        return;
      }

      if (isRecording) {
        recognition.stop();
        setIsRecording(false);
      } else {
        recognition.start();
        setIsRecording(true);
      }
    };

    // 发送消息
    const handleSendClick = () => {
      const trimmedValue = value.trim();
      if (trimmedValue && !disabled && !isLoading) {
        onSend(trimmedValue);
        setValue("");
        setSelectedImage(null);
      }
    };

    const canSend = value.trim() && !disabled && !isLoading;

    return (
      <div className="flex flex-col gap-3">
        {/* 图片预览 */}
        {selectedImage && (
          <div className="relative inline-block animate-in fade-in zoom-in-95 duration-200">
            <img
              src={selectedImage}
              alt="Selected"
              className="max-h-28 rounded-xl border shadow-sm"
            />
            <button
              onClick={handleRemoveImage}
              className="absolute -top-2 -right-2 p-1.5 bg-destructive text-destructive-foreground rounded-full shadow-md hover:bg-destructive/90 transition-colors"
            >
              <span className="sr-only">移除图片</span>
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}

        <div className="flex items-end gap-2">
          {/* 图片上传按钮 */}
          <input
            type="file"
            ref={fileInputRef}
            accept="image/*"
            onChange={handleImageSelect}
            className="hidden"
          />
          <Button
            variant="ghost"
            size="icon"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || isLoading}
            className="shrink-0 hover:bg-muted"
            title="上传图片"
          >
            <Image className="w-4 h-4" />
          </Button>

          {/* 语音输入按钮 */}
          <Button
            variant={isRecording ? "destructive" : "ghost"}
            size="icon"
            onClick={toggleVoiceInput}
            disabled={disabled || isLoading || !recognition}
            className={cn(
              "shrink-0 transition-all",
              isRecording && "animate-pulse"
            )}
            title={isRecording ? "停止录音" : "语音输入"}
          >
            {isRecording ? (
              <MicOff className="w-4 h-4" />
            ) : (
              <Mic className="w-4 h-4" />
            )}
          </Button>

          {/* 文本输入 */}
          <div className="relative flex-1">
            <Textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendClick();
                }
              }}
              placeholder={placeholder}
              disabled={disabled || isLoading}
              className={cn(
                "min-h-[44px] max-h-[150px] resize-none pr-12 transition-all",
                isLoading && "opacity-70"
              )}
              rows={1}
            />

            {/* 加载指示器 */}
            {isLoading && (
              <div className="absolute right-3 top-1/2 -translate-y-1/2">
                <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
              </div>
            )}
          </div>

          {/* 发送按钮 */}
          <Button
            onClick={handleSendClick}
            disabled={!canSend}
            size="icon"
            className={cn(
              "shrink-0 transition-all",
              canSend && "animate-in zoom-in-95"
            )}
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>

        {/* 录音状态提示 */}
        {isRecording && (
          <div className="flex items-center gap-2 text-sm text-destructive animate-pulse">
            <div className="w-2 h-2 bg-destructive rounded-full" />
            <span>正在聆听...</span>
          </div>
        )}

        {/* 提示文字 */}
        <p className="text-[10px] text-muted-foreground text-center">
          按 Enter 发送，Shift + Enter 换行
        </p>
      </div>
    );
  }
);

ChatInput.displayName = "ChatInput";
