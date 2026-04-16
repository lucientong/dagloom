import { useEffect, useState } from 'react';
import { GitBranch, X, Hash, Calendar, FileText } from 'lucide-react';
import { PipelineVersion } from '../types';

interface VersionHistoryProps {
  pipelineId: string;
  getVersions: (id: string) => Promise<PipelineVersion[]>;
  onClose: () => void;
}

export default function VersionHistory({
  pipelineId,
  getVersions,
  onClose,
}: VersionHistoryProps) {
  const [versions, setVersions] = useState<PipelineVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getVersions(pipelineId)
      .then((data) => {
        if (!cancelled) {
          setVersions(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError('Failed to fetch version history.');
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [pipelineId, getVersions]);

  return (
    <div className="w-80 h-full bg-bg/80 backdrop-blur-xl border-l border-bg-light flex flex-col animate-in slide-in-from-right duration-300">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-bg-light">
        <div className="flex items-center gap-2">
          <GitBranch size={16} className="text-primary" />
          <h2 className="text-sm font-semibold text-text-primary">Version History</h2>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-bg-light transition-colors cursor-pointer"
        >
          <X size={16} className="text-text-muted" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5">
        {loading && (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-text-muted">Loading versions...</span>
          </div>
        )}

        {error && !loading && (
          <div className="text-xs text-text-muted text-center py-8">
            {error}
          </div>
        )}

        {!loading && !error && versions.length === 0 && (
          <p className="text-xs text-text-muted text-center py-8">
            No versions found for this pipeline.
          </p>
        )}

        {!loading && !error && versions.length > 0 && (
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-3 top-2 bottom-2 w-px bg-bg-light" />

            <div className="space-y-3">
              {versions.map((version) => {
                const isExpanded = expandedVersion === version.version;
                return (
                  <button
                    key={version.version}
                    onClick={() =>
                      setExpandedVersion(isExpanded ? null : version.version)
                    }
                    className="relative w-full text-left pl-8 pr-3 py-3 rounded-lg hover:bg-bg-light/30 transition-colors cursor-pointer"
                  >
                    {/* Timeline dot */}
                    <div
                      className={`absolute left-1.5 top-4 w-3 h-3 rounded-full border-2 ${
                        isExpanded
                          ? 'bg-primary border-primary'
                          : 'bg-bg border-bg-light'
                      }`}
                    />

                    {/* Version number */}
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-text-primary">
                        v{version.version}
                      </span>
                    </div>

                    {/* Hash & date */}
                    <div className="flex items-center gap-3 mt-1">
                      <span className="flex items-center gap-1 text-[10px] text-text-muted font-mono">
                        <Hash size={9} />
                        {version.hash.slice(0, 8)}
                      </span>
                      <span className="flex items-center gap-1 text-[10px] text-text-muted">
                        <Calendar size={9} />
                        {new Date(version.created_at).toLocaleDateString()}
                      </span>
                    </div>

                    {/* Expanded details */}
                    {isExpanded && (
                      <div className="mt-3 p-3 rounded-lg bg-bg-dark/50 border border-bg-light">
                        <div className="flex items-start gap-2">
                          <FileText size={12} className="text-text-muted mt-0.5 shrink-0" />
                          <div className="space-y-1.5">
                            <p className="text-xs text-text-secondary">
                              {version.description || 'No description'}
                            </p>
                            <p className="text-[10px] text-text-muted font-mono break-all">
                              Full hash: {version.hash}
                            </p>
                            <p className="text-[10px] text-text-muted">
                              {new Date(version.created_at).toLocaleString()}
                            </p>
                          </div>
                        </div>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
