"use client";

import React from "react";
import { cn } from "@/lib/utils";
import {
  Search,
  FileText,
  CheckCircle2,
  XCircle,
  Loader2,
  Sparkles,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import type { RAGQuery } from "@/types";

interface RAGRetrievalProps {
  ragQueries: RAGQuery[];
  className?: string;
}

export function RAGRetrievalDisplay({ ragQueries, className }: RAGRetrievalProps) {
  if (!ragQueries || ragQueries.length === 0) {
    return null;
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <Search className="w-3 h-3" />
        <span>知识库检索</span>
        <span className="ml-1 px-1 py-0.5 rounded bg-blue-100 text-blue-700 text-[10px] dark:bg-blue-900/30 dark:text-blue-400">
          {ragQueries.length}
        </span>
      </div>

      <div className="space-y-2">
        {ragQueries.map((query, index) => (
          <RAGQueryCard key={index} query={query} />
        ))}
      </div>
    </div>
  );
}

function RAGQueryCard({ query }: { query: RAGQuery }) {
  const [expanded, setExpanded] = React.useState(false);

  const StatusIcon = {
    completed: <CheckCircle2 className="w-3 h-3 text-green-500" />,
    failed: <XCircle className="w-3 h-3 text-red-500" />,
    running: <Loader2 className="w-3 h-3 text-blue-500 animate-spin" />,
  };

  return (
    <div className="border rounded-lg overflow-hidden bg-card">
      {/* 标题行 */}
      <div
        className="flex items-center gap-2 p-2 cursor-pointer hover:bg-muted/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="w-3 h-3 text-muted-foreground" />
        ) : (
          <ChevronRight className="w-3 h-3 text-muted-foreground" />
        )}
        <Search className="w-3.5 h-3.5 text-blue-500" />
        <span className="text-xs font-medium flex-1 truncate">
          {query.query}
        </span>
        {StatusIcon[query.status]}
        {query.duration_ms !== undefined && (
          <span className="text-[10px] text-muted-foreground">
            {query.duration_ms.toFixed(0)}ms
          </span>
        )}
      </div>

      {/* 详情内容 */}
      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          {/* 相关性得分 */}
          {query.relevance_scores.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] text-muted-foreground">相关性得分</div>
              <div className="flex items-center gap-1">
                {query.relevance_scores.map((score, idx) => (
                  <div key={idx} className="flex items-center gap-0.5">
                    <div
                      className={cn(
                        "w-8 h-2 rounded-full overflow-hidden bg-gray-200 dark:bg-gray-700"
                      )}
                    >
                      <div
                        className={cn(
                          "h-full rounded-full",
                          score >= 0.9 ? "bg-green-500" :
                          score >= 0.7 ? "bg-blue-500" :
                          score >= 0.5 ? "bg-yellow-500" : "bg-gray-400"
                        )}
                        style={{ width: `${score * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-muted-foreground">
                      {(score * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 检索到的文档 */}
          {query.retrieved_docs.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] text-muted-foreground">
                检索结果 ({query.retrieved_docs.length})
              </div>
              <div className="space-y-1">
                {query.retrieved_docs.map((doc, idx) => {
                  const isSelected = doc === query.selected_doc;
                  return (
                    <div
                      key={idx}
                      className={cn(
                        "flex items-start gap-1 p-1.5 rounded text-xs",
                        isSelected
                          ? "bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800"
                          : "bg-muted/30"
                      )}
                    >
                      <FileText className={cn(
                        "w-3 h-3 shrink-0 mt-0.5",
                        isSelected ? "text-blue-500" : "text-muted-foreground"
                      )} />
                      <span className="flex-1 line-clamp-2 text-muted-foreground">
                        {doc}
                      </span>
                      {isSelected && (
                        <span className="shrink-0 px-1 py-0.5 rounded bg-blue-500 text-white text-[10px]">
                          已选
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 错误信息 */}
          {query.error && (
            <div className="text-xs text-red-500 flex items-center gap-1">
              <XCircle className="w-3 h-3" />
              {query.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// 简化版 RAG 显示
export function RAGRetrievalBadge({ ragQueries }: { ragQueries: RAGQuery[] }) {
  if (!ragQueries || ragQueries.length === 0) {
    return null;
  }

  return (
    <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 text-[10px] dark:bg-blue-900/30 dark:text-blue-400">
      <Search className="w-3 h-3" />
      <span>RAG {ragQueries.length}</span>
    </div>
  );
}
