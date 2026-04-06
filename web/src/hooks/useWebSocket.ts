import { useEffect, useRef, useState, useCallback } from 'react';
import { WSMessage } from '../types';

interface UseWebSocketOptions {
  pipelineId: string;
  onMessage?: (msg: WSMessage) => void;
  autoConnect?: boolean;
}

export function useWebSocket({ pipelineId, onMessage, autoConnect = true }: UseWebSocketOptions) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${pipelineId}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setConnected(true);
      console.info(`[WS] Connected to pipeline ${pipelineId}`);
    };

    ws.onmessage = (event) => {
      const msg: WSMessage = JSON.parse(event.data);
      onMessage?.(msg);
    };

    ws.onclose = () => {
      setConnected(false);
      console.info(`[WS] Disconnected from pipeline ${pipelineId}`);
      // Auto-reconnect after 3s.
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = (err) => {
      console.error('[WS] Error:', err);
    };

    wsRef.current = ws;
  }, [pipelineId, onMessage]);

  const disconnect = useCallback(() => {
    clearTimeout(reconnectTimer.current);
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  useEffect(() => {
    if (autoConnect) {
      connect();
    }
    return () => disconnect();
  }, [autoConnect, connect, disconnect]);

  return { connected, connect, disconnect };
}
