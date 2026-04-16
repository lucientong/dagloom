/** Type definitions for Dagloom Web UI. */

export interface PipelineNode {
  name: string;
  id: string;
  description?: string;
  params?: {
    retry?: number;
    cache?: boolean;
    timeout?: number | null;
  };
}

export interface PipelineEdge {
  source: string;
  target: string;
}

export interface Pipeline {
  id: string;
  name: string;
  description: string;
  node_count: number;
  edge_count: number;
  updated_at: string;
}

export type NodeStatusType = 'pending' | 'running' | 'success' | 'failed' | 'skipped';

export interface ExecutionStatus {
  execution_id: string;
  pipeline_id: string;
  status: NodeStatusType;
  started_at?: string;
  finished_at?: string;
  error_message?: string;
}

export interface DagStructure {
  nodes: PipelineNode[];
  edges: string[][];
}

export interface WSMessage {
  type: 'node_status' | 'log' | 'execution_started' | 'execution_resumed' | 'dag_updated';
  execution_id?: string;
  node_id?: string;
  status?: string;
  message?: string;
  level?: string;
  error_message?: string;
}

export interface LogEntry {
  timestamp: string;
  node_id: string;
  message: string;
  level: 'info' | 'warning' | 'error';
}

export interface NodeMetric {
  node_id: string;
  success_count: number;
  failure_count: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
}

export interface PipelineMetrics {
  pipeline_id: string;
  total_runs: number;
  nodes: NodeMetric[];
}

export interface PipelineVersion {
  version: number;
  hash: string;
  description: string;
  created_at: string;
}

export const NODE_STATUS_COLORS: Record<NodeStatusType, string> = {
  pending: '#94A3B8',
  running: '#3B82F6',
  success: '#22C55E',
  failed: '#EF4444',
  skipped: '#F59E0B',
};
