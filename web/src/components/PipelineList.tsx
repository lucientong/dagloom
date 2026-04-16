import { Layers, ChevronRight } from 'lucide-react';
import { Pipeline } from '../types';

interface PipelineListProps {
  pipelines: Pipeline[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (pipeline: Pipeline) => void;
}

export default function PipelineList({
  pipelines,
  selectedId,
  loading,
  onSelect,
}: PipelineListProps) {
  if (loading) {
    return (
      <div className="w-64 bg-bg/80 backdrop-blur-xl border-r border-bg-light flex flex-col shrink-0">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-bg-light">
          <Layers size={14} className="text-primary" />
          <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Pipelines
          </h3>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="flex flex-col items-center gap-2">
            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-text-muted">Loading...</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-64 bg-bg/80 backdrop-blur-xl border-r border-bg-light flex flex-col shrink-0">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-bg-light">
        <Layers size={14} className="text-primary" />
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          Pipelines
        </h3>
        <span className="ml-auto text-[10px] text-text-muted font-mono">
          {pipelines.length}
        </span>
      </div>

      {/* Pipeline items */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {pipelines.length === 0 ? (
          <p className="text-xs text-text-muted text-center py-8 px-3">
            No pipelines found. Start the backend server or check your connection.
          </p>
        ) : (
          pipelines.map((pipeline) => {
            const isSelected = pipeline.id === selectedId;
            return (
              <button
                key={pipeline.id}
                onClick={() => onSelect(pipeline)}
                className={`
                  w-full text-left px-3 py-2.5 rounded-lg transition-all cursor-pointer
                  ${
                    isSelected
                      ? 'bg-primary/15 border border-primary/30'
                      : 'hover:bg-bg-light/50 border border-transparent'
                  }
                `}
              >
                <div className="flex items-center justify-between">
                  <span
                    className={`text-sm font-medium truncate ${
                      isSelected ? 'text-primary-lighter' : 'text-text-primary'
                    }`}
                  >
                    {pipeline.name}
                  </span>
                  <ChevronRight
                    size={12}
                    className={`shrink-0 ${
                      isSelected ? 'text-primary' : 'text-text-muted'
                    }`}
                  />
                </div>
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-[10px] text-text-muted">
                    {pipeline.node_count} nodes
                  </span>
                  <span className="text-[10px] text-text-muted">
                    {new Date(pipeline.updated_at).toLocaleDateString()}
                  </span>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
