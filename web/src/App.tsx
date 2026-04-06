import { useState, useCallback } from 'react';
import { Node, Edge, MarkerType } from 'reactflow';
import DagEditor from './components/DagEditor';
import Toolbar from './components/Toolbar';
import NodePanel from './components/NodePanel';
import ExecutionLog from './components/ExecutionLog';
import { NodeStatusType, LogEntry } from './types';

// Demo pipeline data for showcase.
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

export default function App() {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>(demoLogs);
  const [isRunning, setIsRunning] = useState(true);
  // Node statuses can be updated via WebSocket in production
  const [nodeStatuses] = useState<Record<string, NodeStatusType>>({});

  const selectedNodeData = selectedNode
    ? demoNodes.find((n) => n.id === selectedNode)?.data
    : null;

  const handleRun = useCallback(() => {
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
  }, []);

  const handleResume = useCallback(() => {
    setLogs((prev) => [
      ...prev,
      {
        timestamp: new Date().toISOString(),
        node_id: 'system',
        message: 'Resuming from last checkpoint ...',
        level: 'info',
      },
    ]);
  }, []);

  return (
    <div className="h-screen flex flex-col bg-bg-dark">
      <Toolbar
        pipelineName="ETL Pipeline"
        isRunning={isRunning}
        isConnected={true}
        onRun={handleRun}
        onResume={handleResume}
        onSave={() => {}}
        onExport={() => {}}
      />

      <div className="flex-1 flex overflow-hidden">
        {/* DAG Editor */}
        <div className="flex-1">
          <DagEditor
            initialNodes={demoNodes}
            initialEdges={demoEdges}
            nodeStatuses={nodeStatuses}
            onNodeSelect={setSelectedNode}
          />
        </div>

        {/* Node Panel (right sidebar) */}
        {selectedNode && selectedNodeData && (
          <NodePanel
            nodeId={selectedNode}
            nodeName={selectedNodeData.label}
            description={selectedNodeData.description}
            status={selectedNodeData.status}
            retry={selectedNodeData.retry}
            cache={selectedNodeData.cache}
            timeout={selectedNodeData.timeout}
            onClose={() => setSelectedNode(null)}
          />
        )}
      </div>

      {/* Execution Log */}
      <ExecutionLog logs={logs} />
    </div>
  );
}
