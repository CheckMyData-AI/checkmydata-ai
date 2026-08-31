/** Human labels for pipeline step keys (shared by the pill + Overview cards). */
export const STEP_LABELS: Record<string, string> = {
  pipeline_start: "Starting...",
  resolve_ssh_key: "SSH Key",
  clone_or_pull: "Git Clone/Pull",
  detect_changes: "Detect Changes",
  cleanup_deleted: "Cleanup Deleted",
  analyze_files: "Analyze Files",
  project_profile: "Project Profile",
  cross_file_analysis: "Cross-File Analysis",
  // The flag-gated repo-index steps. Every one was missing, so a run spent 12 minutes in
  // `graph_build` and 26 in `code_symbol_embed` showing the raw key — the fallback in
  // ActiveTasksWidget is `|| task.currentStep`, which never looks broken enough to report.
  ast_parse: "AST Parse",
  graph_build: "Build Code Graph",
  code_symbol_embed: "Embed Code Symbols",
  bm25_build: "Build BM25",
  schema_embed: "Embed Schema",
  graph_db_bridge: "Code→DB Lineage",
  graph_clustering: "Cluster Communities",
  generate_docs: "Generate Docs",
  record_index: "Record Index",
  // daily_sync composes the three pipelines above.
  repo_index: "Repository Index",
  db_index: "Database Index",
  code_db_sync: "Code-DB Sync",
  introspect_schema: "Introspect Schema",
  fetch_samples: "Fetch Samples",
  load_context: "Load Context",
  validate_tables: "LLM Analysis",
  store_results: "Store Results",
  generate_summary: "Generate Summary",
  load_code_knowledge: "Load Code Knowledge",
  load_db_index: "Load DB Index",
  match_tables: "Match Tables",
  analyze_sync: "Analyze Code-DB",
  store_sync: "Store Results",
  generate_sync_summary: "Generate Summary",
  plan_targets: "Plan Targets",
  freshness_reconcile: "Freshness Reconcile",
  summarize: "Summarize",
  pipeline_end: "Done",
};

export function stepLabel(step: string | null | undefined): string {
  if (!step) return "";
  return STEP_LABELS[step] || step;
}
