/**
 * 前端 API 客户端
 */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  agentName?: string;
  metadata?: Record<string, any>;
  raw?: Record<string, unknown>;
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
