import { useState, useCallback, useEffect } from 'react';
import { Node, Edge, MarkerType } from 'reactflow';
import DagEditor from './components/DagEditor';
import Toolbar from './components/Toolbar';
import NodePanel from './components/NodePanel';
import ExecutionLog from './components/ExecutionLog';
import PipelineList from './components/PipelineList';
import MetricsDashboard from './components/MetricsDashboard';
import VersionHistory from './components/VersionHistory';
import { usePipeline } from './hooks/usePipeline';
import { useWebSocket } from './hooks/useWebSocket';
import { NodeStatusType, LogEntry, Pipeline, WSMessage } from './types';

// Demo pipeline data — used as fallback when the backend is unreachable.
const demoNodes: Node[] = [
  {
    id: 'fetch_data',
    type: 'dagNode',
    position: { x: 300, y: 50 },
    data: {
      label: 'fetch_data',
      description: 'Fetch CSV data from a remote URL',
      status: 'success' as NodeStatusType,
      retry: 3,
      cache: true,
      timeout: 30,
    },
  },
  {
    id: 'validate',
    type: 'dagNode',
    position: { x: 120, y: 200 },
    data: {
      label: 'validate',
      description: 'Validate data schema with Pydantic',
      status: 'success' as NodeStatusType,
      cache: false,
    },
  },
  {
    id: 'clean',
    type: 'dagNode',
    position: { x: 480, y: 200 },
    data: {
      label: 'clean',
      description: 'Remove rows with missing values',
      status: 'running' as NodeStatusType,
      cache: true,
    },
  },
  {
    id: 'transform',
    type: 'dagNode',
    position: { x: 300, y: 370 },
    data: {
      label: 'transform',
      description: 'Apply feature engineering transforms',
      status: 'pending' as NodeStatusType,
      retry: 2,
    },
  },
  {
    id: 'save',
    type: 'dagNode',
    position: { x: 300, y: 520 },
    data: {
      label: 'save',
      description: 'Persist cleaned data to parquet file',
      status: 'pending' as NodeStatusType,
    },
  },
];

const demoEdges: Edge[] = [
  {
    id: 'e1', source: 'fetch_data', target: 'validate', type: 'smoothstep', animated: true,
    style: { stroke: '#6366F1', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6366F1', width: 16, height: 16 },
  },
  {
    id: 'e2', source: 'fetch_data', target: 'clean', type: 'smoothstep', animated: true,
    style: { stroke: '#6366F1', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6366F1', width: 16, height: 16 },
  },
  {
    id: 'e3', source: 'validate', target: 'transform', type: 'smoothstep', animated: true,
    style: { stroke: '#6366F1', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6366F1', width: 16, height: 16 },
  },
  {
    id: 'e4', source: 'clean', target: 'transform', type: 'smoothstep', animated: true,
    style: { stroke: '#6366F1', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6366F1', width: 16, height: 16 },
  },
  {
    id: 'e5', source: 'transform', target: 'save', type: 'smoothstep', animated: true,
    style: { stroke: '#6366F1', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6366F1', width: 16, height: 16 },
  },
];

const demoLogs: LogEntry[] = [
  { timestamp: new Date().toISOString(), node_id: 'fetch_data', message: 'Fetching data from https://example.com/data.csv ...', level: 'info' },
  { timestamp: new Date().toISOString(), node_id: 'fetch_data', message: 'Downloaded 15,234 rows in 2.3s', level: 'info' },
  { timestamp: new Date().toISOString(), node_id: 'fetch_data', message: 'Node completed successfully', level: 'info' },
  { timestamp: new Date().toISOString(), node_id: 'validate', message: 'Schema validation passed — all 12 columns match Pydantic model', level: 'info' },
  { timestamp: new Date().toISOString(), node_id: 'clean', message: 'Processing 15,234 rows ...', level: 'info' },
  { timestamp: new Date().toISOString(), node_id: 'clean', message: 'Dropped 142 rows with missing values (0.9%)', level: 'warning' },
];

/** Convert API DAG structure to ReactFlow nodes/edges. */
function dagToReactFlow(
  dagNodes: { id: string; name: string; description?: string; params?: { retry?: number; cache?: boolean; timeout?: number | null } }[],
  dagEdges: string[][],
): { nodes: Node[]; edges: Edge[] } {
  const spacing = { x: 300, y: 170 };
  const nodes: Node[] = dagNodes.map((n, idx) => ({
    id: n.id,
    type: 'dagNode',
    position: { x: (idx % 3) * spacing.x + 100, y: Math.floor(idx / 3) * spacing.y + 50 },
    data: {
      label: n.name,
      description: n.description ?? '',
      status: 'pending' as NodeStatusType,
      retry: n.params?.retry,
      cache: n.params?.cache,
      timeout: n.params?.timeout,
    },
  }));

  const edges: Edge[] = dagEdges.map(([source, target], idx) => ({
    id: `e-${idx}`,
    source,
    target,
    type: 'smoothstep',
    animated: true,
    style: { stroke: '#6366F1', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6366F1', width: 16, height: 16 },
  }));

  return { nodes, edges };
}

type RightPanel = 'node' | 'metrics' | 'versions' | null;

export default function App() {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>(demoLogs);
  const [isRunning, setIsRunning] = useState(false);
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, NodeStatusType>>({});
  const [toast, setToast] = useState<{ message: string; level: 'error' | 'info' } | null>(null);

  // Pipeline state
  const [activePipelineId, setActivePipelineId] = useState<string | null>(null);
  const [activePipelineName, setActivePipelineName] = useState('ETL Pipeline');
  const [activeNodes, setActiveNodes] = useState<Node[]>(demoNodes);
  const [activeEdges, setActiveEdges] = useState<Edge[]>(demoEdges);
  const [usingDemo, setUsingDemo] = useState(true);

  // Right panel
  const [rightPanel, setRightPanel] = useState<RightPanel>(null);

  // Pipeline API hook
  const {
    pipelines,
    loading: pipelinesLoading,
    error: apiError,
    clearError,
    fetchPipelines,
    runPipeline,
    resumePipeline,
    getDag,
    getMetrics,
    getVersions,
  } = usePipeline();

  // WebSocket hook for real-time updates
  const handleWsMessage = useCallback(
    (msg: WSMessage) => {
      if (msg.type === 'node_status' && msg.node_id && msg.status) {
        setNodeStatuses((prev) => ({
          ...prev,
          [msg.node_id!]: msg.status as NodeStatusType,
        }));
      }

      if (msg.type === 'log' && msg.node_id && msg.message) {
        setLogs((prev) => [
          ...prev,
          {
            timestamp: new Date().toISOString(),
            node_id: msg.node_id!,
            message: msg.message!,
            level: (msg.level as LogEntry['level']) || 'info',
          },
        ]);
      }

      if (msg.type === 'execution_started') {
        setIsRunning(true);
        setLogs((prev) => [
          ...prev,
          {
            timestamp: new Date().toISOString(),
            node_id: 'system',
            message: `Execution ${msg.execution_id ?? ''} started`,
            level: 'info',
          },
        ]);
      }

      if (msg.type === 'execution_resumed') {
        setIsRunning(true);
        setLogs((prev) => [
          ...prev,
          {
            timestamp: new Date().toISOString(),
            node_id: 'system',
            message: `Execution ${msg.execution_id ?? ''} resumed`,
            level: 'info',
          },
        ]);
      }
    },
    [],
  );

  const { connected } = useWebSocket({
    pipelineId: activePipelineId ?? '',
    onMessage: handleWsMessage,
    autoConnect: !!activePipelineId,
  });

  // Show toast on API errors
  useEffect(() => {
    if (apiError) {
      setToast({ message: apiError, level: 'error' });
      clearError();
    }
  }, [apiError, clearError]);

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  // Fetch pipelines on mount (fall back to demo if API unavailable)
  useEffect(() => {
    fetchPipelines().then((data) => {
      if (data.length === 0) {
        setUsingDemo(true);
      }
    });
  }, [fetchPipelines]);

  // Load a pipeline from the API
  const handleSelectPipeline = useCallback(
    async (pipeline: Pipeline) => {
      setActivePipelineId(pipeline.id);
      setActivePipelineName(pipeline.name);
      setSelectedNode(null);
      setRightPanel(null);
      setNodeStatuses({});

      const dag = await getDag(pipeline.id);
      if (dag) {
        const { nodes, edges } = dagToReactFlow(dag.nodes, dag.edges);
        setActiveNodes(nodes);
        setActiveEdges(edges);
        setUsingDemo(false);
      } else {
        setToast({ message: 'Failed to load pipeline DAG — using demo data', level: 'error' });
      }
    },
    [getDag],
  );

  const handleRun = useCallback(async () => {
    if (!activePipelineId) {
      // Demo mode: just add a log entry
      setIsRunning(true);
      setLogs((prev) => [
        ...prev,
        {
          timestamp: new Date().toISOString(),
          node_id: 'system',
          message: 'Pipeline execution started (demo mode)',
          level: 'info',
        },
      ]);
      return;
    }

    try {
      setIsRunning(true);
      setLogs((prev) => [
        ...prev,
        {
          timestamp: new Date().toISOString(),
          node_id: 'system',
          message: 'Pipeline execution started',
          level: 'info',
        },
      ]);
      await runPipeline(activePipelineId);
    } catch (err) {
      setIsRunning(false);
      const msg = err instanceof Error ? err.message : 'Run failed';
      setToast({ message: msg, level: 'error' });
    }
  }, [activePipelineId, runPipeline]);

  const handleResume = useCallback(async () => {
    if (!activePipelineId) {
      setLogs((prev) => [
        ...prev,
        {
          timestamp: new Date().toISOString(),
          node_id: 'system',
          message: 'Resuming from last checkpoint ... (demo mode)',
          level: 'info',
        },
      ]);
      return;
    }

    try {
      setLogs((prev) => [
        ...prev,
        {
          timestamp: new Date().toISOString(),
          node_id: 'system',
          message: 'Resuming from last checkpoint ...',
          level: 'info',
        },
      ]);
      await resumePipeline(activePipelineId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Resume failed';
      setToast({ message: msg, level: 'error' });
    }
  }, [activePipelineId, resumePipeline]);

  const handleNodeSelect = useCallback((nodeId: string | null) => {
    setSelectedNode(nodeId);
    if (nodeId) {
      setRightPanel('node');
    } else {
      setRightPanel(null);
    }
  }, []);

  const selectedNodeData = selectedNode
    ? activeNodes.find((n) => n.id === selectedNode)?.data
    : null;

  return (
    <div className="h-screen flex flex-col bg-bg-dark">
      <Toolbar
        pipelineName={activePipelineName}
        isRunning={isRunning}
        isConnected={connected || usingDemo}
        onRun={handleRun}
        onResume={handleResume}
        onSave={() => {}}
        onExport={() => {}}
      />

      <div className="flex-1 flex overflow-hidden">
        {/* Pipeline list sidebar */}
        <PipelineList
          pipelines={pipelines}
          selectedId={activePipelineId}
          loading={pipelinesLoading}
          onSelect={handleSelectPipeline}
        />

        {/* DAG Editor */}
        <div className="flex-1 relative">
          {/* Panel toggle buttons */}
          <div className="absolute top-3 right-3 z-10 flex items-center gap-1.5">
            <button
              onClick={() => setRightPanel(rightPanel === 'metrics' ? null : 'metrics')}
              disabled={!activePipelineId}
              className={`px-2.5 py-1.5 rounded-lg text-[10px] font-medium transition-colors cursor-pointer
                ${rightPanel === 'metrics' ? 'bg-primary/20 text-primary-lighter border border-primary/30' : 'bg-bg/60 text-text-muted hover:bg-bg-light/50 border border-bg-light'}
                disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              Metrics
            </button>
            <button
              onClick={() => setRightPanel(rightPanel === 'versions' ? null : 'versions')}
              disabled={!activePipelineId}
              className={`px-2.5 py-1.5 rounded-lg text-[10px] font-medium transition-colors cursor-pointer
                ${rightPanel === 'versions' ? 'bg-primary/20 text-primary-lighter border border-primary/30' : 'bg-bg/60 text-text-muted hover:bg-bg-light/50 border border-bg-light'}
                disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              Versions
            </button>
          </div>

          <DagEditor
            initialNodes={activeNodes}
            initialEdges={activeEdges}
            nodeStatuses={nodeStatuses}
            onNodeSelect={handleNodeSelect}
          />
        </div>

        {/* Right panel */}
        {rightPanel === 'node' && selectedNode && selectedNodeData && (
          <NodePanel
            nodeId={selectedNode}
            nodeName={selectedNodeData.label}
            description={selectedNodeData.description}
            status={selectedNodeData.status}
            retry={selectedNodeData.retry}
            cache={selectedNodeData.cache}
            timeout={selectedNodeData.timeout}
            onClose={() => {
              setSelectedNode(null);
              setRightPanel(null);
            }}
          />
        )}
        {rightPanel === 'metrics' && activePipelineId && (
          <MetricsDashboard
            pipelineId={activePipelineId}
            getMetrics={getMetrics}
            onClose={() => setRightPanel(null)}
          />
        )}
        {rightPanel === 'versions' && activePipelineId && (
          <VersionHistory
            pipelineId={activePipelineId}
            getVersions={getVersions}
            onClose={() => setRightPanel(null)}
          />
        )}
      </div>

      {/* Execution Log */}
      <ExecutionLog logs={logs} />

      {/* Error / info toast */}
      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-50 max-w-sm px-4 py-3 rounded-lg shadow-xl border backdrop-blur-md animate-in slide-in-from-bottom duration-300 ${
            toast.level === 'error'
              ? 'bg-danger/15 border-danger/30 text-danger'
              : 'bg-info/15 border-info/30 text-info'
          }`}
        >
          <div className="flex items-start gap-2">
            <span className="text-xs font-medium">{toast.message}</span>
            <button
              onClick={() => setToast(null)}
              className="shrink-0 text-current opacity-70 hover:opacity-100 cursor-pointer"
            >
              &times;
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
