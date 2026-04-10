// 聊天相关类型定义
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  agentName?: string;
  metadata?: Record<string, any>;
  raw?: Record<string, unknown>;
  /** 标记该消息是否因新请求而中断 */
  isInterrupted?: boolean;
}

export interface ChatRequest {
  sessionId?: string;
  userId?: string;
  message: string;
  stream: boolean;
  context?: Record<string, any>;
}

export interface ChatResponse {
  sessionId: string;
  messageId: string;
  content: string;
  agentResults: AgentResult[];
  itinerary?: Itinerary;
  usage: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
}

export interface AgentResult {
  agentName: string;
  success: boolean;
  content: string;
  data?: Record<string, any>;
  toolsUsed: string[];
  executionTimeMs: number;
  error?: string;
}

export interface Itinerary {
  id?: string;
  destination: string;
  startDate: string;
  endDate: string;
  days: DayPlan[];
  totalBudget: number;
  estimatedCost: number;
  currency: string;
  summary?: string;
}

export interface DayPlan {
  date: string;
  dayNumber: number;
  attractions: PlannedAttraction[];
  transports: Transport[];
  totalCost: number;
  totalDurationMinutes: number;
  tips: string[];
}

export interface PlannedAttraction {
  attraction: Attraction;
  arrivalTime: string;
  departureTime: string;
  ticketBooking: boolean;
  notes?: string;
}

export interface Attraction {
  poiId: string;
  name: string;
  location: Location;
  rating: number;
  reviewCount: number;
  tags: string[];
  category: string;
  description?: string;
  openingHours?: string;
  ticketPrice?: number;
  recommendedDuration: number;
  accessibilityScore: number;
  images: string[];
}

export interface Location {
  latitude: number;
  longitude: number;
  address?: string;
  city?: string;
}

export interface Transport {
  type: string;
  fromLocation: string;
  toLocation: string;
  distanceKm: number;
  durationMinutes: number;
  cost: number;
  description?: string;
}

export interface UserPreferences {
  travelStyles: string[];
  budgetLevel: "economy" | "medium" | "luxury";
  touristType: string;
  preferredSeasons: string[];
  dietaryRestrictions: string[];
  mobilityRequirements: string[];
}

export interface Session {
  sessionId: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  preferences: UserPreferences;
  tripContext: TripContext;
}

export interface TripContext {
  destination?: string;
  departurePlace?: string;
  startDate?: string;
  endDate?: string;
  durationDays?: number;
  numTravelers: number;
  travelerAges: number[];
  isDomestic: boolean;
  plannedDays: any[];
}

// 流式事件类型
export type StreamEventType =
  | "message"
  | "agent_start"
  | "agent_complete"
  | "agent_step"
  | "thinking_step"
  | "streaming"
  | "final"
  | "error";

export interface StreamEvent {
  type: StreamEventType;
  data: any;
}

// 对话模式
export type DialogMode = "planning" | "qa" | "chat";

// 情感状态
export type EmotionType = "neutral" | "happy" | "excited" | "frustrated" | "confused" | "worried" | "satisfied";

// 处理状态
export interface ProcessingState {
  phase: string;
  message: string;
  completed: boolean;
  agentName?: string;
}

// Agent 思考步骤 - 增强版
export interface ReasoningNode {
  content: string;
  reasoning_type: "analysis" | "inference" | "decision" | "fact";
  confidence: number;
  children?: ReasoningNode[];
}

export interface ToolCall {
  tool_name: string;
  arguments: Record<string, any>;
  result?: string;
  status: "pending" | "running" | "completed" | "failed";
  duration_ms?: number;
  error?: string;
}

// 外部 API 调用记录
export interface APICall {
  service: string;        // 服务名称，如 "高德地图API"
  endpoint: string;      // API 端点
  params: Record<string, any>;  // 请求参数
  response?: Record<string, any>;  // 响应数据（脱敏后）
  status: "pending" | "running" | "completed" | "failed";
  http_status?: number;   // HTTP 状态码
  duration_ms?: number;   // 执行时长（毫秒）
  error?: string;         // 错误信息
}

export interface AgentMetrics {
  agent_name: string;
  execution_time_ms: number;
  tokens_used: number;
  tool_calls_count: number;
  status: "pending" | "running" | "completed";
}

// RAG 检索记录
export interface RAGQuery {
  query: string;           // 检索查询
  retrieved_docs: string[]; // 检索到的文档摘要
  relevance_scores: number[]; // 相关性得分
  selected_doc?: string;    // 最终选择的文档
  status: "running" | "completed" | "failed";
  duration_ms?: number;
  error?: string;
}

// 用户学习步骤
export interface LearningStep {
  user_action: string;    // 用户行为描述
  system_learned: string; // 系统学习到的内容
  confidence: number;     // 置信度
  category: "preference" | "behavior" | "budget" | "timing";
  timestamp?: string;
}

// Agent 执行时间线事件（用于甘特图）
export interface AgentTimelineEvent {
  agent: string;
  phase: string;           // 执行阶段
  start_ms: number;        // 相对于请求开始的起始时间(ms)
  duration_ms: number;     // 持续时间(ms)
  status: "pending" | "running" | "completed" | "failed";
  is_parallel: boolean;    // 是否并行执行
  dependencies?: string[]; // 依赖的Agent
}

export interface ThinkingStep {
  agent: string;
  step: string;
  detail: string;
  status: "pending" | "running" | "completed" | "failed";
  timestamp?: string;
  // 增强字段
  reasoning_chain?: ReasoningNode[];
  tool_calls?: ToolCall[];
  api_calls?: APICall[];  // 外部API调用
  rag_queries?: RAGQuery[];  // RAG检索
  learning_steps?: LearningStep[];  // 用户学习
  context?: Record<string, any>;
  confidence?: number;
  sub_steps?: ThinkingStep[];
  waiting_for?: string[];
}

// 获取推理节点图标
export const getReasoningIcon = (type: ReasoningNode["reasoning_type"]): string => {
  const icons: Record<ReasoningNode["reasoning_type"], string> = {
    analysis: "🔍",
    inference: "🤔",
    decision: "✅",
    fact: "📌",
  };
  return icons[type] || "💡";
};

// 获取状态颜色
export const getStatusColor = (status: ThinkingStep["status"]): string => {
  const colors: Record<ThinkingStep["status"], string> = {
    pending: "text-gray-400",
    running: "text-blue-500",
    completed: "text-green-500",
    failed: "text-red-500",
  };
  return colors[status] || "text-gray-400";
};
