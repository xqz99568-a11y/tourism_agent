"use client";

import React, { useMemo } from "react";
import { cn } from "@/lib/utils";

interface MarkdownRendererProps {
  content: string;
  isUser?: boolean;
}

// 常见主题的 emoji 映射
const topicEmojis: Record<string, string> = {
  "景点": "🗺️",
  "美食": "🍜",
  "餐厅": "🍽️",
  "推荐": "⭐",
  "特色": "✨",
  "必游": "📍",
  "攻略": "📖",
  "交通": "🚗",
  "住宿": "🏨",
  "购物": "🛍️",
  "娱乐": "🎭",
  "活动": "🎪",
  "季节": "🌸",
  "天气": "🌤️",
  "预算": "💰",
  "费用": "💵",
  "建议": "💡",
  "注意": "⚠️",
  "提示": "🔔",
  "时间": "⏰",
  "开放": "🕐",
  "门票": "🎫",
  "地址": "📍",
  "路线": "🛤️",
  "距离": "📏",
  "时长": "⏱️",
  "人数": "👥",
  "适合": "👌",
  "评价": "⭐",
  "评分": "🌟",
};

// 自动为标题添加 emoji
function addEmojiToTitle(text: string): { emoji: string | null; text: string } {
  for (const [topic, emoji] of Object.entries(topicEmojis)) {
    if (text.includes(topic)) {
      return { emoji, text };
    }
  }
  return { emoji: null, text };
}

function getKeySnippet(value: unknown): string {
  const raw =
    typeof value === "string"
      ? value
      : (() => {
          try {
            return JSON.stringify(value);
          } catch {
            return String(value ?? "");
          }
        })();

  return raw.replace(/\s+/g, " ").trim().slice(0, 20);
}

function buildContentKey(prefix: string, index: number, value: unknown): string {
  return `${prefix}-${index}-${getKeySnippet(value)}`;
}

/**
 * 简单的 Markdown 渲染器 - 增强版
 * 支持: 标题、加粗、列表、代码块、链接、Emoji
 */
export function MarkdownRenderer({ content, isUser = false }: MarkdownRendererProps) {
  const rendered = useMemo(() => {
    if (!content) return null;

    // 如果是纯文本（用户消息），直接返回
    if (isUser) {
      return <span className="whitespace-pre-wrap">{content}</span>;
    }

    // 分割行
    const lines = content.split("\n");
    const elements: React.ReactNode[] = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];
      const trimmedLine = line.trim();

      // 空行
      if (!trimmedLine) {
        i++;
        continue;
      }

      // 标题 (# ## ###)
      const headingMatch = trimmedLine.match(/^(#{1,3})\s+(.+)$/);
      if (headingMatch) {
        const level = headingMatch[1].length;
        const text = headingMatch[2];
        const { emoji, text: cleanText } = addEmojiToTitle(text);
        const Tag = `h${level}` as keyof JSX.IntrinsicElements;
        elements.push(
          <Tag key={buildContentKey("heading", i, cleanText)} className={getHeadingClass(level)}>
            {emoji && <span className="mr-2">{emoji}</span>}
            {renderInline(cleanText)}
          </Tag>
        );
        i++;
        continue;
      }

      // 分隔线
      if (trimmedLine === "---" || trimmedLine === "***" || trimmedLine === "___") {
        elements.push(<hr key={buildContentKey("hr", i, trimmedLine)} className="my-4 border-border/50" />);
        i++;
        continue;
      }

      // 表格开始
      if (trimmedLine.startsWith("|")) {
        const tableLines: string[] = [];
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          tableLines.push(lines[i]);
          i++;
        }
        elements.push(<TableRenderer key={buildContentKey("table", i, tableLines)} lines={tableLines} />);
        continue;
      }

      // 列表 (- 或 * 或数字.)
      if (trimmedLine.match(/^[-*]\s/) || trimmedLine.match(/^\d+\.\s/)) {
        const listItems: string[] = [];
        while (
          i < lines.length &&
          (lines[i].trim().match(/^[-*]\s/) || lines[i].trim().match(/^\d+\.\s/))
        ) {
          listItems.push(lines[i]);
          i++;
        }
        elements.push(<ListRenderer key={buildContentKey("list", i, listItems)} items={listItems} />);
        continue;
      }

      // 引用块
      if (trimmedLine.startsWith(">")) {
        const quoteLines: string[] = [];
        while (i < lines.length && lines[i].trim().startsWith(">")) {
          quoteLines.push(lines[i].replace(/^>\s?/, ""));
          i++;
        }
        elements.push(
          <blockquote
            key={buildContentKey("quote", i, quoteLines.join(" "))}
            className="border-l-3 border-primary/50 pl-4 my-3 py-2 rounded-r-lg bg-primary/5 dark:bg-primary/10"
          >
            {renderInline(quoteLines.join(" "))}
          </blockquote>
        );
        continue;
      }

      // 代码块
      if (trimmedLine.startsWith("```")) {
        const codeLines: string[] = [];
        const lang = trimmedLine.slice(3);
        i++;
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          codeLines.push(lines[i]);
          i++;
        }
        i++; // 跳过结束 ```
        elements.push(
          <pre key={buildContentKey("code", i, `${lang} ${codeLines.join(" ")}`)} className="bg-muted rounded-lg p-3 my-3 overflow-x-auto text-xs border border-border/50">
            <code>{codeLines.join("\n")}</code>
          </pre>
        );
        continue;
      }

      // 普通段落
      const paraLines: string[] = [line];
      while (
        i + 1 < lines.length &&
        lines[i + 1].trim() &&
        !lines[i + 1].trim().match(/^#{1,3}\s/) &&
        !lines[i + 1].trim().startsWith("|") &&
        !lines[i + 1].trim().match(/^[-*]\s/)
      ) {
        i++;
        paraLines.push(lines[i]);
      }
      elements.push(
        <p key={`p-${i}-${paraLines.join(" ").slice(0, 20)}`} className="my-2 leading-relaxed">
          {renderInline(paraLines.join(" "))}
        </p>
      );
      i++;
    }

    return <div className="space-y-1">{elements}</div>;
  }, [content, isUser]);

  return <div className="whitespace-pre-wrap">{rendered}</div>;
}

function getHeadingClass(level: number): string {
  switch (level) {
    case 1:
      return "text-xl font-bold mt-5 mb-3 flex items-center";
    case 2:
      return "text-lg font-semibold mt-4 mb-2 flex items-center";
    case 3:
      return "text-base font-medium mt-3 mb-1.5 flex items-center";
    default:
      return "";
  }
}

function renderInline(text: string): React.ReactNode {
  // 处理加粗 **text**
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  while (remaining) {
    const boldMatch = remaining.match(/\*\*(.+?)\*\*/);
    if (boldMatch) {
      const index = remaining.indexOf(boldMatch[0])!;
      if (index > 0) {
        parts.push(<span key={key++}>{remaining.slice(0, index)}</span>);
      }
      parts.push(<strong key={key++} className="font-semibold">{boldMatch[1]}</strong>);
      remaining = remaining.slice(index + boldMatch[0].length);
    } else {
      parts.push(<span key={key++}>{remaining}</span>);
      break;
    }
  }

  return parts;
}

interface TableRendererProps {
  lines: string[];
}

function TableRenderer({ lines }: TableRendererProps) {
  if (lines.length < 2) return null;

  const headers = lines[0]
    .split("|")
    .filter((_, i) => i !== 0 && i !== lines[0].split("|").length - 1)
    .map((h) => h.trim());

  const rows = lines
    .slice(2) // 跳过表头和分隔符
    .map((line) =>
      line
        .split("|")
        .filter((_, i) => i !== 0 && i !== line.split("|").length - 1)
        .map((c) => c.trim())
    );

  return (
    <div className="overflow-x-auto my-3 rounded-lg border border-border/50">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-muted/50 border-b border-border">
            {headers.map((header, i) => (
              <th key={`${i}-${header.slice(0, 20)}`} className="px-4 py-2.5 text-left font-medium text-muted-foreground">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${i}-${JSON.stringify(row).slice(0, 20)}`} className="border-b border-border/30 hover:bg-muted/30 transition-colors">
              {row.map((cell, j) => (
                <td key={`${j}-${cell.slice(0, 20)}`} className="px-4 py-2.5">
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ListRendererProps {
  items: string[];
}

function ListRenderer({ items }: ListRendererProps) {
  const isOrdered = items[0].trim().match(/^\d+\.\s/);

  // 根据内容选择合适的 emoji
  const getItemEmoji = (item: string): string => {
    const lowerItem = item.toLowerCase();
    if (lowerItem.includes("景点") || lowerItem.includes("地方")) return "📍";
    if (lowerItem.includes("美食") || lowerItem.includes("餐厅") || lowerItem.includes("菜")) return "🍽️";
    if (lowerItem.includes("推荐") || lowerItem.includes("建议")) return "💡";
    if (lowerItem.includes("时间") || lowerItem.includes("开放")) return "⏰";
    if (lowerItem.includes("门票") || lowerItem.includes("价格") || lowerItem.includes("费用")) return "💰";
    if (lowerItem.includes("地址")) return "📮";
    if (lowerItem.includes("必游")) return "⭐";
    return "✨";
  };

  return (
    <ul className={cn("space-y-2 my-3 ml-4", isOrdered ? "list-decimal" : "space-y-2")}>
      {items.map((item, i) => {
        const cleanItem = item.replace(/^[-*]\s/, "").replace(/^\d+\.\s/, "");
        const emoji = isOrdered ? `${i + 1}.` : getItemEmoji(cleanItem);
        return (
          <li key={`${i}-${cleanItem.slice(0, 20)}`} className="leading-relaxed flex items-start gap-2">
            {!isOrdered && <span className="text-base flex-shrink-0 mt-0.5">{emoji}</span>}
            {isOrdered && <span className="font-medium text-primary/70 mr-1">{emoji}</span>}
            <span className="flex-1">{renderInline(cleanItem)}</span>
          </li>
        );
      })}
    </ul>
  );
}
