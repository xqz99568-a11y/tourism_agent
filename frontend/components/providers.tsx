"use client";

import React, { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useChatStore, useUIStore } from "@/stores/chat-store";

interface ProvidersProps {
  children: React.ReactNode;
}

const INIT_TIMEOUT_MS = 3000;
const PERSISTED_STORAGE_KEYS = ["tourism-chat-storage", "tourism-ui-storage"] as const;

function withTimeout<T>(promise: Promise<T>, timeoutMs: number) {
  return new Promise<T>((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      reject(new Error("页面初始化超时，请刷新重试"));
    }, timeoutMs);

    promise.then(
      (value) => {
        window.clearTimeout(timeoutId);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timeoutId);
        reject(error);
      }
    );
  });
}

function clearPersistedState() {
  for (const key of PERSISTED_STORAGE_KEYS) {
    try {
      window.localStorage.removeItem(key);
    } catch (error) {
      console.error(`Failed to clear persisted cache "${key}":`, error);
    }
  }
}

function validatePersistedState() {
  for (const key of PERSISTED_STORAGE_KEYS) {
    const rawValue = window.localStorage.getItem(key);

    if (!rawValue) {
      continue;
    }

    try {
      JSON.parse(rawValue);
    } catch {
      throw new Error(`本地缓存 "${key}" 已损坏，请刷新重试`);
    }
  }
}

function markStoresHydrated() {
  try {
    useChatStore.getState().setHasHydrated(true);
  } catch (error) {
    console.error("Failed to mark chat store hydrated:", error);
  }

  try {
    useUIStore.getState().setHasHydrated(true);
  } catch (error) {
    console.error("Failed to mark UI store hydrated:", error);
  }
}

export function Providers({ children }: ProvidersProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            gcTime: 10 * 60 * 1000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: 1,
          },
        },
      })
  );
  const [isInitializing, setIsInitializing] = useState(true);
  const [initError, setInitError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const initialize = async () => {
      let nextError: string | null = null;

      try {
        validatePersistedState();

        await withTimeout(
          Promise.all([
            Promise.resolve(useChatStore.persist.rehydrate()),
            Promise.resolve(useUIStore.persist.rehydrate()),
          ]),
          INIT_TIMEOUT_MS
        );
      } catch (error) {
        console.error("Failed to initialize persisted state:", error);
        clearPersistedState();
        nextError =
          error instanceof Error && error.message
            ? error.message
            : "页面初始化失败，请刷新重试";
      } finally {
        markStoresHydrated();

        if (!cancelled) {
          setInitError(nextError);
          setIsInitializing(false);
        }
      }
    };

    initialize();

    return () => {
      cancelled = true;
    };
  }, []);

  if (isInitializing) {
    return (
      <QueryClientProvider client={queryClient}>
        <div className="flex min-h-screen items-center justify-center bg-background">
          <div className="flex flex-col items-center gap-4">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
            <p className="text-sm text-muted-foreground">加载中...</p>
          </div>
        </div>
      </QueryClientProvider>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <>
        {initError && (
          <div className="border-b border-destructive/20 bg-destructive/10 px-4 py-3">
            <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
              <p className="text-sm text-foreground">
                初始化失败，已跳过异常缓存并继续进入页面。请刷新重试。
              </p>
              <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
                刷新重试
              </Button>
            </div>
          </div>
        )}
        {children}
      </>
    </QueryClientProvider>
  );
}
