// Barrel module consolidating the split-per-domain api surfaces (T28).
// Individual callers can ``import { projects, types }`` directly, but the
// legacy ``import { api, Project } from "@/lib/api"`` shape is preserved
// via this index so no existing code has to change.

export * from "./types";
export {
  handleSessionExpired,
  resetSessionExpiredFlag,
  API_BASE,
  request,
  getCsrfToken,
  getCsrfHeaders,
} from "./_client";

import { auth, mcpTokens } from "./auth";
import { billing } from "./billing";
import { projects } from "./projects";
import { connections } from "./connections";
import { chat } from "./chat";
import { runs } from "./runs";
import {
  batch,
  dashboards,
  demo,
  invites,
  models,
  notes,
  notifications,
  repos,
  rules,
  schedules,
  sshKeys,
  tasks,
  usage,
  viz,
} from "./workspace";
import {
  dataGraph,
  dataValidation,
  explore,
  feed,
  insights,
  logs,
  reconciliation,
  semanticLayer,
  temporal,
} from "./analytics";

export {
  auth,
  batch,
  billing,
  mcpTokens,
  chat,
  connections,
  dashboards,
  dataGraph,
  dataValidation,
  demo,
  explore,
  feed,
  insights,
  invites,
  logs,
  models,
  notes,
  notifications,
  projects,
  reconciliation,
  repos,
  rules,
  runs,
  schedules,
  semanticLayer,
  sshKeys,
  tasks,
  temporal,
  usage,
  viz,
};

export const api = {
  auth,
  billing,
  mcpTokens,
  projects,
  connections,
  chat,
  sshKeys,
  repos,
  runs,
  rules,
  invites,
  notes,
  dashboards,
  models,
  viz,
  tasks,
  dataValidation,
  usage,
  logs,
  schedules,
  notifications,
  batch,
  demo,
  dataGraph,
  feed,
  insights,
  temporal,
  explore,
  semanticLayer,
  reconciliation,
};
