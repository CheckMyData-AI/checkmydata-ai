// Barrel module consolidating the split-per-domain api surfaces (T28).
// Individual callers can ``import { projects, types }`` directly, but the
// legacy ``import { api, Project } from "@/lib/api"`` shape is preserved
// via this index so no existing code has to change.

export * from "./types";
export { handleSessionExpired, API_BASE, request, getAuthHeaders } from "./_client";

import { auth } from "./auth";
import { projects } from "./projects";
import { connections } from "./connections";
import { chat } from "./chat";
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
  projects,
  connections,
  chat,
  sshKeys,
  repos,
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
