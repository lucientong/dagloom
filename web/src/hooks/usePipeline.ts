import { useState, useCallback } from 'react';
import { Pipeline, ExecutionStatus, DagStructure } from '../types';

const API_BASE = '/api';

export function usePipeline() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPipelines = useCallback(async () => {
    setLoading(true);
    setError(null);
    const res = await fetch(`${API_BASE}/pipelines`);
    if (!res.ok) {
      setError(`Failed to fetch pipelines: ${res.statusText}`);
      setLoading(false);
      return;
    }
    const data = await res.json();
    setPipelines(data);
    setLoading(false);
  }, []);

  const runPipeline = useCallback(async (pipelineId: string, inputs: Record<string, unknown> = {}) => {
    const res = await fetch(`${API_BASE}/pipelines/${pipelineId}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs }),
    });
    if (!res.ok) {
      const detail = await res.json();
      throw new Error(detail.detail || 'Failed to run pipeline');
    }
    return (await res.json()) as ExecutionStatus;
  }, []);

  const resumePipeline = useCallback(async (pipelineId: string) => {
    const res = await fetch(`${API_BASE}/pipelines/${pipelineId}/resume`, {
      method: 'POST',
    });
    if (!res.ok) {
      const detail = await res.json();
      throw new Error(detail.detail || 'Failed to resume pipeline');
    }
    return (await res.json()) as ExecutionStatus;
  }, []);

  const getPipelineStatus = useCallback(async (pipelineId: string) => {
    const res = await fetch(`${API_BASE}/pipelines/${pipelineId}/status`);
    if (!res.ok) return null;
    return (await res.json()) as ExecutionStatus;
  }, []);

  const getDag = useCallback(async (pipelineId: string) => {
    const res = await fetch(`${API_BASE}/pipelines/${pipelineId}/dag`);
    if (!res.ok) return null;
    return (await res.json()) as DagStructure;
  }, []);

  const updateDag = useCallback(async (pipelineId: string, dag: DagStructure) => {
    const res = await fetch(`${API_BASE}/pipelines/${pipelineId}/dag`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dag),
    });
    return res.ok;
  }, []);

  return {
    pipelines,
    loading,
    error,
    fetchPipelines,
    runPipeline,
    resumePipeline,
    getPipelineStatus,
    getDag,
    updateDag,
  };
}
