import { describe, it, expect, beforeEach } from "vitest";
import { useTaskStore } from "@/stores/task-store";
import type { PipelineStatusResponse } from "@/lib/api/types";

describe("task-store seedFromPipelineStatus", () => {
  beforeEach(() => {
    useTaskStore.setState({ tasks: {}, pinnedRunningIds: new Set() });
  });

  it("seeds running repo and sync tasks from pipeline status", () => {
    const status: PipelineStatusResponse = {
      project_id: "proj-1",
      any_running: true,
      repo: {
        is_indexing: true,
        checkpoint_status: "running",
        workflow_id: "wf-repo",
        last_indexed_at: null,
        last_indexed_commit: null,
      },
      connections: [
        {
          connection_id: "conn-1",
          connection_name: "Main DB",
          db_index: {
            is_indexing: false,
            indexing_status: "completed",
            indexed_at: null,
            table_count: 10,
          },
          code_db_sync: {
            is_syncing: true,
            sync_status: "running",
            synced_at: null,
            total_tables: 10,
            synced_tables: 2,
          },
        },
      ],
    };

    useTaskStore.getState().seedFromPipelineStatus(status);

    const tasks = useTaskStore.getState().tasks;
    expect(tasks["wf-repo"]?.pipeline).toBe("index_repo");
    expect(tasks["wf-repo"]?.status).toBe("running");
    expect(tasks["sync:conn-1"]?.pipeline).toBe("code_db_sync");
    expect(useTaskStore.getState().pinnedRunningIds.has("sync:conn-1")).toBe(true);
  });
});
