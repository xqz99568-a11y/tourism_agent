import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown, Send, MessageSquare } from 'lucide-react';

interface FeedbackComponentProps {
  onSubmit: (feedback: { rating: 'positive' | 'negative'; comment?: string }) => void;
}

function FeedbackComponent({ onSubmit }: FeedbackComponentProps) {
  const [rating, setRating] = useState<'positive' | 'negative' | null>(null);
  const [comment, setComment] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  const handleRating = (value: 'positive' | 'negative') => {
    setRating(value);
  };

  const handleSubmit = async () => {
    if (!rating) return;
    
    setIsSubmitting(true);
    try {
      await onSubmit({ rating, comment: comment.trim() });
      setIsSubmitted(true);
    } catch (error) {
      console.error('Feedback submission failed:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isSubmitted) {
    return (
      <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400">
        <Send className="h-4 w-4" />
        <span>感谢您的反馈！</span>
      </div>
    );
  }

  return (
    <div className="mt-4 pt-4 border-t border-border/70">
      <div className="flex items-center gap-4 mb-3">
        <span className="text-sm font-medium text-slate-900 dark:text-slate-50">对这个回答满意吗？</span>
        <div className="flex gap-2">
          <button
            onClick={() => handleRating('positive')}
            className={`p-2 rounded-full transition-all ${rating === 'positive' ? 'bg-emerald-100 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400' : 'hover:bg-slate-100 dark:hover:bg-slate-800'}`}
          >
            <ThumbsUp className="h-4 w-4" />
          </button>
          <button
            onClick={() => handleRating('negative')}
            className={`p-2 rounded-full transition-all ${rating === 'negative' ? 'bg-red-100 text-red-600 dark:bg-red-950/30 dark:text-red-400' : 'hover:bg-slate-100 dark:hover:bg-slate-800'}`}
          >
            <ThumbsDown className="h-4 w-4" />
          </button>
        </div>
      </div>
      
      {rating && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-slate-500 dark:text-slate-400" />
            <input
              type="text"
              placeholder={rating === 'positive' ? '分享一下为什么满意？' : '有什么可以改进的地方？'}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="flex-1 rounded-xl border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="flex items-center gap-2 px-4 py-2 rounded-xl border border-sky-500 bg-sky-500 text-white text-sm font-medium transition-all hover:bg-sky-600 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Send className="h-4 w-4" />
            {isSubmitting ? '提交中...' : '提交反馈'}
          </button>
        </div>
      )}
    </div>
  );
}

export { FeedbackComponent };