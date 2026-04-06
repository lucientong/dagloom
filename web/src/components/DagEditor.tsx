import { useCallback, useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  BackgroundVariant,
  MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';
import DagNode from './DagNode';
import { NodeStatusType, NODE_STATUS_COLORS } from '../types';

interface DagEditorProps {
  initialNodes?: Node[];
  initialEdges?: Edge[];
  nodeStatuses?: Record<string, NodeStatusType>;
  onNodeSelect?: (nodeId: string | null) => void;
  onDagChange?: (nodes: Node[], edges: Edge[]) => void;
}

const nodeTypes = { dagNode: DagNode };

const defaultEdgeOptions = {
  type: 'smoothstep',
  animated: true,
  style: { stroke: '#6366F1', strokeWidth: 2 },
  markerEnd: { type: MarkerType.ArrowClosed, color: '#6366F1', width: 16, height: 16 },
};

export default function DagEditor({
  initialNodes = [],
  initialEdges = [],
  nodeStatuses = {},
  onNodeSelect,
  onDagChange,
}: DagEditorProps) {
  const [nodes, _setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds) => {
        const updated = addEdge({ ...params, ...defaultEdgeOptions }, eds);
        onDagChange?.(nodes, updated);
        return updated;
      });
    },
    [setEdges, nodes, onDagChange]
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect?.(node.id);
    },
    [onNodeSelect]
  );

  const onPaneClick = useCallback(() => {
    onNodeSelect?.(null);
  }, [onNodeSelect]);

  // Update node statuses.
  const styledNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        data: {
          ...node.data,
          status: nodeStatuses[node.id] || node.data.status || 'pending',
        },
      })),
    [nodes, nodeStatuses]
  );

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={styledNodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        className="bg-bg-dark"
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#334155"
        />
        <Controls
          className="!bg-bg/80 !backdrop-blur-md !border-bg-light !rounded-lg !shadow-lg"
        />
        <MiniMap
          nodeColor={(node) => {
            const status = node.data?.status as NodeStatusType;
            return NODE_STATUS_COLORS[status] || '#94A3B8';
          }}
          maskColor="rgba(15, 23, 42, 0.8)"
          className="!bg-bg/60 !backdrop-blur-md !border-bg-light !rounded-lg"
        />
      </ReactFlow>
    </div>
  );
}
