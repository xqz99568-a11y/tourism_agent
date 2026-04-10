import * as React from "react";
import { Send, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

interface AIInputWithLoadingProps {
  onSubmit: (value: string) => void;
  isLoading: boolean;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
}

const AIInputWithLoading = React.forwardRef<HTMLTextAreaElement, AIInputWithLoadingProps>(
  ({ onSubmit, isLoading, disabled, className, ...props }, ref) => {
    const [value, setValue] = React.useState("");
    const [suggestions, setSuggestions] = React.useState<string[]>([]);
    const [showSuggestions, setShowSuggestions] = React.useState(false);

    // 旅游相关的常见输入建议
    const commonSuggestions = [
      "广州出发去杭州玩3天，2个人，预算3000",
      "北京5日游，带老人和小孩",
      "上海周边周末游推荐",
      "三亚度假5天4晚，预算5000",
      "成都重庆7日游，美食路线",
      "西安历史文化之旅",
      "厦门鼓浪屿三日游",
      "云南大理丽江泸沽湖10日游"
    ];

    const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newValue = e.target.value;
      setValue(newValue);

      // 简单的智能提示逻辑
      if (newValue.length > 1) {
        const filtered = commonSuggestions.filter(suggestion =>
          suggestion.toLowerCase().includes(newValue.toLowerCase())
        );
        setSuggestions(filtered);
        setShowSuggestions(filtered.length > 0);
      } else {
        setSuggestions([]);
        setShowSuggestions(false);
      }
    };

    const handleSubmit = (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = value.trim();
      if (trimmed && !isLoading && !disabled) {
        onSubmit(trimmed);
        setValue("");
        setSuggestions([]);
        setShowSuggestions(false);
      }
    };

    const handleSuggestionClick = (suggestion: string) => {
      setValue(suggestion);
      setSuggestions([]);
      setShowSuggestions(false);
    };

    return (
      <form onSubmit={handleSubmit} className="relative">
        <textarea
          ref={ref}
          value={value}
          onChange={handleInputChange}
          disabled={isLoading || disabled}
          placeholder="描述你的旅行需求，例如：广州出发去杭州玩3天，2个人，预算3000..."
          className={cn(
            "flex min-h-[80px] w-full rounded-2xl border border-input bg-background px-4 py-3 pr-12 text-base ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
            className
          )}
          {...props}
        />
        <button
          type="submit"
          disabled={isLoading || disabled || !value.trim()}
          className={cn(
            "absolute right-2 bottom-2 rounded-full p-2 transition-all hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50",
            isLoading
              ? "text-muted-foreground"
              : "text-sky-600 hover:bg-sky-100 dark:text-sky-400 dark:hover:bg-sky-950/30"
          )}
        >
          {isLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
        </button>

        {/* 智能提示下拉框 */}
        {showSuggestions && suggestions.length > 0 && (
          <div className="absolute left-0 right-0 top-full mt-1 rounded-2xl border border-input bg-background shadow-lg z-10">
            {suggestions.map((suggestion, index) => (
              <button
                key={index}
                type="button"
                onClick={() => handleSuggestionClick(suggestion)}
                className="w-full text-left px-4 py-2 hover:bg-muted transition-colors text-sm"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
      </form>
    );
  }
);

AIInputWithLoading.displayName = "AIInputWithLoading";

export { AIInputWithLoading };