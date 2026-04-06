import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { NodeStatusType, NODE_STATUS_COLORS } from '../types';
import { RefreshCw, Database, Clock } from 'lucide-react';

interface DagNodeData {
  label: string;
  description?: string;
  status?: NodeStatusType;
  retry?: number;
  cache?: boolean;
  timeout?: number | null;
  selected?: boolean;
}

function DagNode({ data, selected }: NodeProps<DagNodeData>) {
  const status = data.status || 'pending';
  const borderColor = NODE_STATUS_COLORS[status];
  const isRunning = status === 'running';

  return (
    <div
      className={`
        relative group min-w-[180px] rounded-xl
        bg-bg/80 backdrop-blur-md border-2 transition-all duration-300
        hover:shadow-lg hover:shadow-primary/10 hover:-translate-y-0.5
        ${selected ? 'ring-2 ring-primary/50 shadow-lg shadow-primary/20' : ''}
        ${isRunning ? 'animate-pulse-slow' : ''}
      `}
      style={{ borderColor }}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-bg-light !border-2 !border-text-muted hover:!border-primary transition-colors"
      />

      {/* Node content */}
      <div className="px-4 py-3">
        {/* Status indicator */}
        <div className="flex items-center gap-2 mb-1.5">
          <div
            className={`w-2.5 h-2.5 rounded-full ${isRunning ? 'animate-pulse' : ''}`}
            style={{ backgroundColor: borderColor }}
          />
          <span className="text-xs font-medium uppercase tracking-wider text-text-muted">
            {status}
          </span>
        </div>

        {/* Node name */}
        <h3 className="text-sm font-semibold text-text-primary truncate">
          {data.label}
        </h3>

        {/* Description */}
        {data.description && (
          <p className="text-xs text-text-muted mt-1 line-clamp-2">
            {data.description}
          </p>
        )}

        {/* Feature badges */}
        <div className="flex gap-1.5 mt-2">
          {data.retry && data.retry > 0 && (
            <span className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-md bg-warning/15 text-warning">
              <RefreshCw size={10} />
              {data.retry}
            </span>
          )}
          {data.cache && (
            <span className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-md bg-success/15 text-success">
              <Database size={10} />
              cache
            </span>
          )}
          {data.timeout && (
            <span className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-md bg-info/15 text-info">
              <Clock size={10} />
              {data.timeout}s
            </span>
          )}
        </div>
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !bg-bg-light !border-2 !border-text-muted hover:!border-primary transition-colors"
      />

      {/* Hover glow effect */}
      <div
        className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
        style={{
          background: `radial-gradient(ellipse at center, ${borderColor}10 0%, transparent 70%)`,
        }}
      />
    </div>
  );
}

export default memo(DagNode);
