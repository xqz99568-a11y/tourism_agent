"use client";

import { useEffect, useRef } from "react";

type AutoResizeOptions = {
  value: string;
  minHeight?: number;
  maxHeight?: number;
};

export function useAutoResizeTextarea({
  value,
  minHeight = 88,
  maxHeight = 220,
}: AutoResizeOptions) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) {
      return;
    }

    element.style.height = `${minHeight}px`;
    const nextHeight = Math.min(element.scrollHeight, maxHeight);
    element.style.height = `${Math.max(nextHeight, minHeight)}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [maxHeight, minHeight, value]);

  const reset = () => {
    const element = textareaRef.current;
    if (!element) {
      return;
    }

    element.style.height = `${minHeight}px`;
    element.style.overflowY = "hidden";
  };

  return {
    textareaRef,
    reset,
  };
}
