import { useState, useCallback } from 'react';
import {
  Pipeline,
  ExecutionStatus,
  DagStructure,
  PipelineMetrics,
  PipelineVersion,
} from '../types';

const API_BASE = '/api';

export function usePipeline() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => setError(null), []);

  const fetchPipelines = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/pipelines`);
      if (!res.ok) {
        setError(`Failed to fetch pipelines: ${res.statusText}`);
        setLoading(false);
        return [];
      }
      const data: Pipeline[] = await res.json();
      setPipelines(data);
      setLoading(false);
      return data;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Network error';
      setError(msg);
      setLoading(false);
      return [];
    }
  }, []);

  const runPipeline = useCallback(async (pipelineId: string, inputs: Record<string, unknown> = {}) => {
    setError(null);
    try {
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
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to run pipeline';
      setError(msg);
      throw err;
    }
  }, []);

  const resumePipeline = useCallback(async (pipelineId: string) => {
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/pipelines/${pipelineId}/resume`, {
        method: 'POST',
      });
      if (!res.ok) {
        const detail = await res.json();
        throw new Error(detail.detail || 'Failed to resume pipeline');
      }
      return (await res.json()) as ExecutionStatus;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to resume pipeline';
      setError(msg);
      throw err;
    }
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

  const getMetrics = useCallback(async (pipelineId: string) => {
    try {
      const res = await fetch(`${API_BASE}/metrics/${pipelineId}`);
      if (!res.ok) return null;
      return (await res.json()) as PipelineMetrics;
    } catch {
      return null;
    }
  }, []);

  const getVersions = useCallback(async (pipelineId: string) => {
    try {
      const res = await fetch(`${API_BASE}/pipelines/${pipelineId}/versions`);
      if (!res.ok) return [];
      return (await res.json()) as PipelineVersion[];
    } catch {
      return [];
    }
  }, []);

  const getSecrets = useCallback(async (pipelineId: string) => {
    try {
      const res = await fetch(`${API_BASE}/pipelines/${pipelineId}/secrets`);
      if (!res.ok) return [];
      return (await res.json()) as string[];
    } catch {
      return [];
    }
  }, []);

  return {
    pipelines,
    loading,
    error,
    clearError,
    fetchPipelines,
    runPipeline,
    resumePipeline,
    getPipelineStatus,
    getDag,
    updateDag,
    getMetrics,
    getVersions,
    getSecrets,
  };
}
