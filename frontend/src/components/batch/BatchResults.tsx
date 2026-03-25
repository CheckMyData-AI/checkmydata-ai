"use client";

interface BatchResultsProps {
  batchId: string;
  onClose?: () => void;
  onBack?: () => void;
}

export function BatchResults({ batchId }: BatchResultsProps) {
  return (
    <div className="text-xs text-text-tertiary">
      Batch results for {batchId} (coming soon)
    </div>
  );
}
