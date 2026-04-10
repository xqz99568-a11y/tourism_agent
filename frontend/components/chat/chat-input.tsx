"use client";

import React, { forwardRef, useImperativeHandle, useRef, useEffect, useState, useCallback } from "react";
import { Send, Image, Mic, MicOff, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  disabled?: boolean;
  placeholder?: string;
  onImageSelect?: (imageData: string) => void;
  onVoiceInput?: (text: string) => void;
}

export const ChatInput = forwardRef<HTMLTextAreaElement, ChatInputProps>(
  ({ value, onChange, onSend, onKeyDown, disabled, placeholder, onImageSelect, onVoiceInput }, ref) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [isRecording, setIsRecording] = useState(false);
    const [selectedImage, setSelectedImage] = useState<string | null>(null);
    const [recognition, setRecognition] = useState<any>(null);

    useImperativeHandle(ref, () => textareaRef.current!);

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
      if (typeof window !== "undefined" && ("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
        const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = "zh-CN";

        recognition.onresult = (event: any) => {
          let transcript = "";
          for (let i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
          }
          onChange(transcript);
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
    }, [onChange]);

    // 处理图片选择
    const handleImageSelect = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = (e) => {
          const imageData = e.target?.result as string;
          setSelectedImage(imageData);
          onImageSelect?.(imageData);
        };
        reader.readAsDataURL(file);
      }
      // 重置 input
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }, [onImageSelect]);

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

    return (
      <div className="flex flex-col gap-2">
        {/* 图片预览 */}
        {selectedImage && (
          <div className="relative inline-block">
            <img
              src={selectedImage}
              alt="Selected"
              className="max-h-24 rounded-lg border"
            />
            <button
              onClick={handleRemoveImage}
              className="absolute -top-2 -right-2 p-1 bg-destructive text-destructive-foreground rounded-full"
            >
              <X className="w-3 h-3" />
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
            variant="outline"
            size="icon"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="shrink-0"
            title="上传图片"
          >
            <Image className="w-4 h-4" />
          </Button>

          {/* 语音输入按钮 */}
          <Button
            variant={isRecording ? "destructive" : "outline"}
            size="icon"
            onClick={toggleVoiceInput}
            disabled={disabled || !recognition}
            className="shrink-0"
            title={isRecording ? "停止录音" : "语音输入"}
          >
            {isRecording ? (
              <div className="w-4 h-4 animate-pulse">
                <MicOff className="w-4 h-4" />
              </div>
            ) : (
              <Mic className="w-4 h-4" />
            )}
          </Button>

          {/* 文本输入 */}
          <div className="relative flex-1">
            <Textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={placeholder || "输入消息..."}
              disabled={disabled}
              className="min-h-[44px] max-h-[150px] resize-none pr-12"
              rows={1}
            />
          </div>

          {/* 发送按钮 */}
          <Button
            onClick={onSend}
            disabled={disabled || !value.trim()}
            size="icon"
            className="shrink-0"
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>

        {/* 录音状态提示 */}
        {isRecording && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
            <span>正在聆听...</span>
          </div>
        )}
      </div>
    );
  }
);

ChatInput.displayName = "ChatInput";
