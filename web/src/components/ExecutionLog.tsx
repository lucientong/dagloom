import { useRef, useEffect } from 'react';
import { LogEntry } from '../types';
import { Terminal, AlertCircle, AlertTriangle, Info } from 'lucide-react';

interface ExecutionLogProps {
  logs: LogEntry[];
  maxHeight?: string;
}

const levelIcons = {
  info: <Info size={12} className="text-info" />,
  warning: <AlertTriangle size={12} className="text-warning" />,
  error: <AlertCircle size={12} className="text-danger" />,
};

const levelColors = {
  info: 'text-text-secondary',
  warning: 'text-warning',
  error: 'text-danger',
};

export default function ExecutionLog({ logs, maxHeight = '240px' }: ExecutionLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="bg-bg/80 backdrop-blur-xl border-t border-bg-light flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-bg-light">
        <Terminal size={14} className="text-primary" />
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          Execution Log
        </h3>
        <span className="ml-auto text-[10px] text-text-muted font-mono">
          {logs.length} entries
        </span>
      </div>

      {/* Log entries */}
      <div
        className="overflow-y-auto font-mono text-xs p-3 space-y-0.5"
        style={{ maxHeight }}
      >
        {logs.length === 0 ? (
          <p className="text-text-muted text-center py-8">
            No execution logs yet. Run a pipeline to see output here.
          </p>
        ) : (
          logs.map((log, idx) => (
            <div
              key={idx}
              className={`flex items-start gap-2 py-0.5 px-2 rounded hover:bg-bg-light/30 transition-colors ${levelColors[log.level]}`}
            >
              <span className="mt-0.5 shrink-0">{levelIcons[log.level]}</span>
              <span className="text-text-muted shrink-0 w-16">
                {new Date(log.timestamp).toLocaleTimeString()}
              </span>
              <span className="text-primary-lighter shrink-0 w-24 truncate">
                [{log.node_id}]
              </span>
              <span className="break-all">{log.message}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
