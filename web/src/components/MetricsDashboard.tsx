import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { BarChart3, X } from 'lucide-react';
import { PipelineMetrics, NodeMetric } from '../types';

interface MetricsDashboardProps {
  pipelineId: string;
  getMetrics: (id: string) => Promise<PipelineMetrics | null>;
  onClose: () => void;
}

export default function MetricsDashboard({
  pipelineId,
  getMetrics,
  onClose,
}: MetricsDashboardProps) {
  const [metrics, setMetrics] = useState<PipelineMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getMetrics(pipelineId)
      .then((data) => {
        if (!cancelled) {
          if (data) {
            setMetrics(data);
          } else {
            setError('No metrics available for this pipeline.');
          }
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError('Failed to fetch metrics.');
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [pipelineId, getMetrics]);

  const latencyData = metrics?.nodes.map((n: NodeMetric) => ({
    name: n.node_id,
    avg: Math.round(n.avg_latency_ms),
    p95: Math.round(n.p95_latency_ms),
  })) ?? [];

  const successData = metrics?.nodes.map((n: NodeMetric) => ({
    name: n.node_id,
    success: n.success_count,
    failure: n.failure_count,
  })) ?? [];

  return (
    <div className="w-80 h-full bg-bg/80 backdrop-blur-xl border-l border-bg-light flex flex-col animate-in slide-in-from-right duration-300">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-bg-light">
        <div className="flex items-center gap-2">
          <BarChart3 size={16} className="text-primary" />
          <h2 className="text-sm font-semibold text-text-primary">Metrics</h2>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-bg-light transition-colors cursor-pointer"
        >
          <X size={16} className="text-text-muted" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5 space-y-6">
        {loading && (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-text-muted">Loading metrics...</span>
          </div>
        )}

        {error && !loading && (
          <div className="text-xs text-text-muted text-center py-8">
            {error}
          </div>
        )}

        {metrics && !loading && (
          <>
            {/* Summary */}
            <div className="p-3 rounded-lg bg-bg-dark/50 border border-bg-light">
              <label className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                Total Runs
              </label>
              <p className="text-lg font-bold text-text-primary mt-1">
                {metrics.total_runs}
              </p>
            </div>

            {/* Success / Failure chart */}
            <div>
              <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
                Success / Failure Count
              </h3>
              <div className="h-40 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={successData} barGap={2}>
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 9, fill: '#94A3B8' }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 9, fill: '#94A3B8' }}
                      axisLine={false}
                      tickLine={false}
                      width={30}
                    />
                    <Tooltip
                      contentStyle={{
                        background: '#1E293B',
                        border: '1px solid #334155',
                        borderRadius: 8,
                        fontSize: 11,
                        color: '#F8FAFC',
                      }}
                    />
                    <Bar dataKey="success" stackId="a" radius={[0, 0, 0, 0]}>
                      {successData.map((_, idx) => (
                        <Cell key={idx} fill="#22C55E" />
                      ))}
                    </Bar>
                    <Bar dataKey="failure" stackId="a" radius={[4, 4, 0, 0]}>
                      {successData.map((_, idx) => (
                        <Cell key={idx} fill="#EF4444" />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Latency chart */}
            <div>
              <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
                Latency (ms)
              </h3>
              <div className="h-40 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={latencyData} barGap={2}>
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 9, fill: '#94A3B8' }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 9, fill: '#94A3B8' }}
                      axisLine={false}
                      tickLine={false}
                      width={35}
                    />
                    <Tooltip
                      contentStyle={{
                        background: '#1E293B',
                        border: '1px solid #334155',
                        borderRadius: 8,
                        fontSize: 11,
                        color: '#F8FAFC',
                      }}
                    />
                    <Bar dataKey="avg" name="Avg" radius={[4, 4, 0, 0]}>
                      {latencyData.map((_, idx) => (
                        <Cell key={idx} fill="#6366F1" />
                      ))}
                    </Bar>
                    <Bar dataKey="p95" name="P95" radius={[4, 4, 0, 0]}>
                      {latencyData.map((_, idx) => (
                        <Cell key={idx} fill="#A78BFA" />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Per-node table */}
            <div>
              <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
                Per-Node Details
              </h3>
              <div className="space-y-2">
                {metrics.nodes.map((node) => (
                  <div
                    key={node.node_id}
                    className="p-3 rounded-lg bg-bg-dark/50 border border-bg-light"
                  >
                    <p className="text-xs font-medium text-text-primary truncate">
                      {node.node_id}
                    </p>
                    <div className="flex items-center gap-4 mt-1.5">
                      <span className="text-[10px] text-success">
                        {node.success_count} ok
                      </span>
                      <span className="text-[10px] text-danger">
                        {node.failure_count} fail
                      </span>
                      <span className="text-[10px] text-text-muted">
                        avg {Math.round(node.avg_latency_ms)}ms
                      </span>
                      <span className="text-[10px] text-text-muted">
                        p95 {Math.round(node.p95_latency_ms)}ms
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
