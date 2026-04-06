import { Play, RotateCcw, Save, Download, Wifi, WifiOff } from 'lucide-react';

interface ToolbarProps {
  pipelineName: string;
  isRunning: boolean;
  isConnected: boolean;
  onRun: () => void;
  onResume: () => void;
  onSave: () => void;
  onExport: () => void;
}

export default function Toolbar({
  pipelineName,
  isRunning,
  isConnected,
  onRun,
  onResume,
  onSave,
  onExport,
}: ToolbarProps) {
  return (
    <header className="h-14 bg-bg/80 backdrop-blur-xl border-b border-bg-light flex items-center justify-between px-5 shrink-0">
      {/* Left: Logo + Pipeline name */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xl">🧶</span>
          <span className="text-sm font-bold bg-gradient-to-r from-primary to-primary-lighter bg-clip-text text-transparent">
            Dagloom
          </span>
        </div>
        <div className="w-px h-6 bg-bg-light" />
        <span className="text-sm text-text-secondary font-medium">
          {pipelineName || 'Untitled Pipeline'}
        </span>
      </div>

      {/* Center: Status indicator */}
      <div className="flex items-center gap-2">
        {isRunning && (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-info/10 border border-info/30">
            <div className="w-2 h-2 rounded-full bg-info animate-pulse" />
            <span className="text-xs font-medium text-info">Running</span>
          </div>
        )}
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-full">
          {isConnected ? (
            <Wifi size={12} className="text-success" />
          ) : (
            <WifiOff size={12} className="text-text-muted" />
          )}
          <span className="text-[10px] text-text-muted">
            {isConnected ? 'Connected' : 'Offline'}
          </span>
        </div>
      </div>

      {/* Right: Action buttons */}
      <div className="flex items-center gap-2">
        <button
          onClick={onExport}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:bg-bg-light transition-colors cursor-pointer"
        >
          <Download size={14} />
          Export
        </button>
        <button
          onClick={onSave}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:bg-bg-light transition-colors cursor-pointer"
        >
          <Save size={14} />
          Save
        </button>
        <button
          onClick={onResume}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-warning bg-warning/10 hover:bg-warning/20 border border-warning/30 transition-colors cursor-pointer"
        >
          <RotateCcw size={14} />
          Resume
        </button>
        <button
          onClick={onRun}
          disabled={isRunning}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-gradient-to-r from-primary to-primary-light hover:from-primary-light hover:to-primary-lighter shadow-lg shadow-primary/25 transition-all disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          <Play size={14} />
          {isRunning ? 'Running...' : 'Run'}
        </button>
      </div>
    </header>
  );
}
