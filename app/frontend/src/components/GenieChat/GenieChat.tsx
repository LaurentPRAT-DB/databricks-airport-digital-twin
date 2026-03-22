import { useState, useRef, useEffect, useCallback } from 'react';

interface GenieMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sql?: string;
  columns?: string[];
  data?: (string | number | null)[][];
  rowCount?: number;
  status?: string;
  error?: string;
  timestamp: number;
}

interface GenieApiResponse {
  conversation_id: string | null;
  message_id: string | null;
  status: string;
  sql: string | null;
  columns: string[] | null;
  data: (string | number | null)[][] | null;
  row_count: number;
  text_response: string | null;
  error: string | null;
}

const SAMPLE_QUESTIONS = [
  'How many flights are approaching KJFK right now?',
  'Which gates are most used in the last 6 hours?',
  'Show me all flights at KSFO by phase',
  'Average turnaround time by aircraft type today',
];

const WORKSPACE_URL = 'https://fevm-serverless-stable-3n0ihb.cloud.databricks.com';
const GENIE_SPACE_ID = '01f12612fa6314ae943d0526f5ae3a00';

export default function GenieChat() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<GenieMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  // Focus input when panel opens
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  const sendMessage = useCallback(async (question: string) => {
    if (!question.trim() || isLoading) return;

    const userMsg: GenieMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: question.trim(),
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const endpoint = conversationId ? '/api/genie/followup' : '/api/genie/ask';
      const body = conversationId
        ? { conversation_id: conversationId, question: question.trim() }
        : { question: question.trim() };

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data: GenieApiResponse = await res.json();

      if (data.conversation_id && !conversationId) {
        setConversationId(data.conversation_id);
      }

      const assistantMsg: GenieMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: data.text_response || (data.status === 'COMPLETED' ? 'Query completed.' : `Status: ${data.status}`),
        sql: data.sql || undefined,
        columns: data.columns || undefined,
        data: data.data || undefined,
        rowCount: data.row_count,
        status: data.status,
        error: data.error || undefined,
        timestamp: Date.now(),
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err) {
      const errorMsg: GenieMessage = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: 'Failed to connect to Genie. Please try again.',
        error: err instanceof Error ? err.message : 'Unknown error',
        status: 'ERROR',
        timestamp: Date.now(),
      };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  }, [conversationId, isLoading]);

  const handleNewConversation = () => {
    setMessages([]);
    setConversationId(null);
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  return (
    <>
      {/* Floating Action Button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-4 right-4 z-[1100] w-12 h-12 rounded-full bg-blue-600 hover:bg-blue-500 text-white shadow-lg flex items-center justify-center transition-all hover:scale-105"
          title="Ask Airport Operations Assistant"
          data-testid="genie-fab"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
        </button>
      )}

      {/* Chat Panel */}
      {isOpen && (
        <div
          className="fixed right-0 top-14 bottom-0 w-[400px] z-[1100] bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 flex flex-col shadow-2xl"
          data-testid="genie-panel"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
            <div className="flex items-center gap-2">
              <span className="text-blue-600 dark:text-blue-400">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </span>
              <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Airport Ops Assistant</h3>
            </div>
            <div className="flex items-center gap-1">
              {messages.length > 0 && (
                <button
                  onClick={handleNewConversation}
                  className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
                  title="New conversation"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </button>
              )}
              <a
                href={`${WORKSPACE_URL}/genie/spaces/${GENIE_SPACE_ID}`}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
                title="Open in Databricks Genie"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
                title="Close"
                data-testid="genie-close"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 && !isLoading && (
              <div className="text-center py-8">
                <div className="text-3xl mb-3">&#x2708;&#xFE0F;</div>
                <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
                  Ask me anything about airport operations
                </p>
                <div className="space-y-2">
                  {SAMPLE_QUESTIONS.map((q) => (
                    <button
                      key={q}
                      onClick={() => sendMessage(q)}
                      className="block w-full text-left text-xs px-3 py-2 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-blue-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors border border-slate-200 dark:border-slate-700"
                      data-testid="sample-question"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg) => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                    msg.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : msg.error
                      ? 'bg-red-50 dark:bg-red-900/30 text-red-800 dark:text-red-300 border border-red-200 dark:border-red-800'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200'
                  }`}
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>

                  {/* SQL block */}
                  {msg.sql && <SqlBlock sql={msg.sql} />}

                  {/* Data table */}
                  {msg.columns && msg.data && msg.data.length > 0 && (
                    <DataTable columns={msg.columns} data={msg.data} rowCount={msg.rowCount || 0} />
                  )}
                </div>
              </div>
            ))}

            {/* Loading indicator */}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-slate-100 dark:bg-slate-800 rounded-lg px-4 py-3">
                  <div className="flex gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-2 h-2 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-2 h-2 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Input */}
          <div className="border-t border-slate-200 dark:border-slate-700 p-3">
            <div className="flex gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about flight operations..."
                className="flex-1 px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={isLoading}
                data-testid="genie-input"
              />
              <button
                onClick={() => sendMessage(input)}
                disabled={isLoading || !input.trim()}
                className="px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-400 text-white rounded-lg transition-colors"
                data-testid="genie-send"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** Collapsible SQL code block */
function SqlBlock({ sql }: { sql: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
      >
        <svg className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        SQL Query
      </button>
      {expanded && (
        <pre className="mt-1 p-2 rounded bg-slate-900 text-green-400 text-xs overflow-x-auto max-h-40 scrollbar-thin">
          {sql}
        </pre>
      )}
    </div>
  );
}

/** Compact data table for query results */
function DataTable({
  columns,
  data,
  rowCount,
}: {
  columns: string[];
  data: (string | number | null)[][];
  rowCount: number;
}) {
  const maxDisplay = 10;
  const displayData = data.slice(0, maxDisplay);

  return (
    <div className="mt-2 overflow-x-auto">
      <table className="text-xs w-full border-collapse">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col}
                className="px-2 py-1 text-left font-medium text-slate-500 dark:text-slate-400 border-b border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {displayData.map((row, i) => (
            <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
              {row.map((cell, j) => (
                <td
                  key={j}
                  className="px-2 py-1 border-b border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 max-w-[120px] truncate"
                  title={String(cell ?? '')}
                >
                  {cell ?? '-'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rowCount > maxDisplay && (
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 text-center">
          Showing {maxDisplay} of {rowCount} rows
          <a
            href={`${WORKSPACE_URL}/genie/spaces/${GENIE_SPACE_ID}`}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-1 text-blue-600 dark:text-blue-400 hover:underline"
          >
            View all in Genie
          </a>
        </p>
      )}
    </div>
  );
}
