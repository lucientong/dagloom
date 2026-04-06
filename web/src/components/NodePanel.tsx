import { X, RefreshCw, Database, Clock, Zap } from 'lucide-react';
import { NodeStatusType, NODE_STATUS_COLORS } from '../types';

interface NodePanelProps {
  nodeId: string;
  nodeName: string;
  description?: string;
  status?: NodeStatusType;
  retry?: number;
  cache?: boolean;
  timeout?: number | null;
  onClose: () => void;
}

export default function NodePanel({
  nodeId,
  nodeName,
  description,
  status = 'pending',
  retry = 0,
  cache = false,
  timeout = null,
  onClose,
}: NodePanelProps) {
  const statusColor = NODE_STATUS_COLORS[status];

  return (
    <div className="w-80 h-full bg-bg/80 backdrop-blur-xl border-l border-bg-light flex flex-col animate-in slide-in-from-right duration-300">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-bg-light">
        <div className="flex items-center gap-2">
          <Zap size={16} className="text-primary" />
          <h2 className="text-sm font-semibold text-text-primary">Node Properties</h2>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-bg-light transition-colors cursor-pointer"
        >
          <X size={16} className="text-text-muted" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* Node info */}
        <div className="space-y-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
              Name
            </label>
            <p className="text-sm text-text-primary font-medium mt-0.5">{nodeName}</p>
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
              ID
            </label>
            <p className="text-xs text-text-secondary font-mono mt-0.5">{nodeId}</p>
          </div>

          {description && (
            <div>
              <label className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                Description
              </label>
              <p className="text-xs text-text-secondary mt-0.5">{description}</p>
            </div>
          )}
        </div>

        {/* Status */}
        <div className="p-3 rounded-lg bg-bg-dark/50 border border-bg-light">
          <label className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
            Status
          </label>
          <div className="flex items-center gap-2 mt-1.5">
            <div
              className={`w-3 h-3 rounded-full ${status === 'running' ? 'animate-pulse' : ''}`}
              style={{ backgroundColor: statusColor }}
            />
            <span className="text-sm font-medium capitalize" style={{ color: statusColor }}>
              {status}
            </span>
          </div>
        </div>

        {/* Configuration */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Configuration
          </h3>

          {/* Retry */}
          <div className="flex items-center justify-between p-3 rounded-lg bg-bg-dark/50 border border-bg-light">
            <div className="flex items-center gap-2">
              <RefreshCw size={14} className="text-warning" />
              <span className="text-xs text-text-secondary">Retry</span>
            </div>
            <span className="text-sm font-mono text-text-primary">{retry}</span>
          </div>

          {/* Cache */}
          <div className="flex items-center justify-between p-3 rounded-lg bg-bg-dark/50 border border-bg-light">
            <div className="flex items-center gap-2">
              <Database size={14} className="text-success" />
              <span className="text-xs text-text-secondary">Cache</span>
            </div>
            <span className={`text-sm font-medium ${cache ? 'text-success' : 'text-text-muted'}`}>
              {cache ? 'Enabled' : 'Disabled'}
            </span>
          </div>

          {/* Timeout */}
          <div className="flex items-center justify-between p-3 rounded-lg bg-bg-dark/50 border border-bg-light">
            <div className="flex items-center gap-2">
              <Clock size={14} className="text-info" />
              <span className="text-xs text-text-secondary">Timeout</span>
            </div>
            <span className="text-sm font-mono text-text-primary">
              {timeout ? `${timeout}s` : 'None'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
