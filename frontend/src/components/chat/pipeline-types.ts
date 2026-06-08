export type PipelineStageStatus =
  | "pending"
  | "running"
  | "passed"
  | "failed"
  | "checkpoint"
  | "skipped"
  | "validating";

export interface CheckpointPreview {
  columns?: string[];
  sampleRows?: unknown[][];
  summary?: string;
  rowCount?: number;
}

export interface PipelineStage {
  id: string;
  description: string;
  tool: string;
  checkpoint: boolean;
  status: PipelineStageStatus;
  rowCount?: number;
  columns?: string[];
  error?: string;
  warnings?: string[];
  /** Persisted from checkpoint SSE extra */
  checkpointPreview?: CheckpointPreview;
  /** Sub-state while data_gate is active */
  dataGateDetail?: string;
}
