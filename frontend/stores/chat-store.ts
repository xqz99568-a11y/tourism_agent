/**
 * 聊天状态管理 (Zustand)
 */
import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type {
  ChatMessage,
  DialogMode,
  EmotionType,
  ProcessingState,
  AgentResult,
  Itinerary,
  UserPreferences,
  ThinkingStep,
} from "@/types";

// ============================================
// 聊天状态 Store
// ============================================
interface ChatState {
  // 会话
  sessionId: string;
  currentMode: DialogMode;
  detectedEmotion: EmotionType | null;
  
  // 消息
  messages: ChatMessage[];
  isProcessing: boolean;
  
  // 处理状态
  processingStates: ProcessingState[];
  agentResults: AgentResult[];
  
  // Agent 思考步骤
  thinkingSteps: ThinkingStep[];
  
  // 规划结果
  currentItinerary: Itinerary | null;
  
  // 建议
  suggestions: string[];
  
  // 用户偏好
  preferences: UserPreferences | null;
  
  // 动作
  setSessionId: (sessionId: string) => void;
  setCurrentMode: (mode: DialogMode) => void;
  setDetectedEmotion: (emotion: EmotionType | null) => void;
  addMessage: (message: ChatMessage) => void;
  addMessages: (messages: ChatMessage[]) => void;
  setMessages: (messages: ChatMessage[]) => void;
  /** 按 id 合并更新单条消息（用于流式占位与增量更新） */
  patchMessage: (id: string, patch: Partial<ChatMessage>) => void;
  clearMessages: () => void;
  setIsProcessing: (isProcessing: boolean) => void;
  setProcessingStates: (states: ProcessingState[]) => void;
  updateProcessingState: (index: number, state: Partial<ProcessingState>) => void;
  addProcessingState: (state: ProcessingState) => void;
  setAgentResults: (results: AgentResult[]) => void;
  addAgentResult: (result: AgentResult) => void;
  setThinkingSteps: (steps: ThinkingStep[]) => void;
  addThinkingStep: (step: ThinkingStep) => void;
  clearThinkingSteps: () => void;
  setCurrentItinerary: (itinerary: Itinerary | null) => void;
  setSuggestions: (suggestions: string[]) => void;
  setPreferences: (preferences: UserPreferences | null) => void;
  reset: () => void;
  _hasHydrated: boolean;
  setHasHydrated: (state: boolean) => void;
}

// 服务端默认状态
const getDefaultState = () => ({
  sessionId: "",
  currentMode: "planning" as DialogMode,
  detectedEmotion: null as EmotionType | null,
  messages: [] as ChatMessage[],
  isProcessing: false,
  processingStates: [] as ProcessingState[],
  agentResults: [] as AgentResult[],
  thinkingSteps: [] as ThinkingStep[],
  currentItinerary: null as Itinerary | null,
  suggestions: [] as string[],
  preferences: null as UserPreferences | null,
  _hasHydrated: false,
});

export const useChatStore = create<ChatState>()(
  devtools(
    persist(
      (set, get) => ({
        ...getDefaultState(),
        
        setSessionId: (sessionId) => set({ sessionId }),
        
        setCurrentMode: (currentMode) => set({ currentMode }),
        
        setDetectedEmotion: (detectedEmotion) => set({ detectedEmotion }),
        
        addMessage: (message) =>
          set((state) => ({ messages: [...state.messages, message] })),
        
        addMessages: (messages) =>
          set((state) => ({ messages: [...state.messages, ...messages] })),
        
        setMessages: (messages) => set({ messages }),

        patchMessage: (id, patch) =>
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === id ? { ...m, ...patch } : m
            ),
          })),
        
        clearMessages: () => set({ messages: [], currentItinerary: null, suggestions: [] }),
        
        setIsProcessing: (isProcessing) => set({ isProcessing }),
        
        setProcessingStates: (processingStates) => set({ processingStates }),
        
        updateProcessingState: (index, partialState) =>
          set((state) => ({
            processingStates: state.processingStates.map((s, i) =>
              i === index ? { ...s, ...partialState } : s
            ),
          })),
        
        addProcessingState: (state) =>
          set((prev) => ({
            processingStates: [...prev.processingStates, state],
          })),
        
        setAgentResults: (agentResults) => set({ agentResults }),
        
        addAgentResult: (result) =>
          set((state) => ({ agentResults: [...state.agentResults, result] })),
        
        setThinkingSteps: (thinkingSteps) => set({ thinkingSteps }),
        
        addThinkingStep: (step) =>
          set((state) => ({ thinkingSteps: [...state.thinkingSteps, step] })),
        
        clearThinkingSteps: () => set({ thinkingSteps: [] }),
        
        setCurrentItinerary: (currentItinerary) => set({ currentItinerary }),
        
        setSuggestions: (suggestions) => set({ suggestions }),
        
        setPreferences: (preferences) => set({ preferences }),
        
        reset: () => set({
          ...getDefaultState(),
          sessionId: crypto.randomUUID(),
        }),
        
        setHasHydrated: (state) => set({ _hasHydrated: state }),
      }),
      {
        name: "tourism-chat-storage",
        partialize: (state) => ({
          sessionId: state.sessionId,
          messages: state.messages.slice(-50),
        }),
        onRehydrateStorage: () => (state) => {
          // 标记 hydration 完成
          state?.setHasHydrated(true);
        },
      }
    ),
    { name: "ChatStore" }
  )
);

// ============================================
// UI 状态 Store
// ============================================
interface UIState {
  // 侧边栏
  isSidebarOpen: boolean;
  isChainOfThoughtOpen: boolean;
  
  // 主题
  theme: "light" | "dark" | "system";
  
  // 移动端
  isMobile: boolean;
  isMobileMenuOpen: boolean;
  
  // 动作
  toggleSidebar: () => void;
  toggleChainOfThought: () => void;
  setTheme: (theme: "light" | "dark" | "system") => void;
  setIsMobile: (isMobile: boolean) => void;
  toggleMobileMenu: () => void;
  _hasHydrated: boolean;
  setHasHydrated: (state: boolean) => void;
}

const getDefaultUIState = () => ({
  isSidebarOpen: true,
  isChainOfThoughtOpen: false,
  theme: "light" as const,
  isMobile: false,
  isMobileMenuOpen: false,
  _hasHydrated: false,
});

export const useUIStore = create<UIState>()(
  devtools(
    persist(
      (set) => ({
        ...getDefaultUIState(),
        
        toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
        
        toggleChainOfThought: () =>
          set((state) => ({ isChainOfThoughtOpen: !state.isChainOfThoughtOpen })),
        
        setTheme: (theme) => set({ theme }),
        
        setIsMobile: (isMobile) => set({ isMobile }),
        
        toggleMobileMenu: () => set((state) => ({ isMobileMenuOpen: !state.isMobileMenuOpen })),
        
        setHasHydrated: (state) => set({ _hasHydrated: state }),
      }),
      {
        name: "tourism-ui-storage",
        partialize: (state) => ({ theme: state.theme }),
        onRehydrateStorage: () => (state) => {
          state?.setHasHydrated(true);
        },
      }
    ),
    { name: "UIStore" }
  )
);
