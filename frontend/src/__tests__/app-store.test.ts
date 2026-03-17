import { describe, it, expect, beforeEach } from "vitest";
import { useAppStore } from "@/stores/app-store";

const mockProject = {
  id: "p1",
  name: "Test",
  description: "",
  repo_url: null,
  repo_branch: "main",
  ssh_key_id: null,
  indexing_llm_provider: null,
  indexing_llm_model: null,
  agent_llm_provider: null,
  agent_llm_model: null,
  sql_llm_provider: null,
  sql_llm_model: null,
  owner_id: null,
  user_role: null,
};

beforeEach(() => {
  useAppStore.setState({
    projects: [],
    activeProject: null,
    connections: [],
    activeConnection: null,
    chatSessions: [],
    activeSession: null,
    messages: [],
  });
  localStorage.clear();
});

describe("app store", () => {
  it("setActiveProject updates state", () => {
    useAppStore.getState().setActiveProject(mockProject);
    expect(useAppStore.getState().activeProject?.id).toBe("p1");
  });

  it("addMessage appends to messages", () => {
    useAppStore.getState().addMessage({
      id: "m1",
      role: "user",
      content: "Hello",
      timestamp: Date.now(),
    });
    expect(useAppStore.getState().messages).toHaveLength(1);
    expect(useAppStore.getState().messages[0].content).toBe("Hello");
  });

  it("setActiveProject persists ID to localStorage", () => {
    useAppStore.getState().setActiveProject(mockProject);
    expect(localStorage.getItem("active_project_id")).toBe("p1");
  });

  it("setActiveProject(null) clears localStorage keys", () => {
    useAppStore.getState().setActiveProject(mockProject);
    useAppStore.getState().setActiveConnection({
      id: "c1",
      project_id: "p1",
      name: "DB",
      db_type: "postgresql",
      ssh_host: null,
      ssh_port: 22,
      ssh_user: null,
      ssh_key_id: null,
      db_host: "localhost",
      db_port: 5432,
      db_name: "test",
      db_user: null,
      is_read_only: true,
      is_active: true,
      ssh_exec_mode: false,
      ssh_command_template: null,
      ssh_pre_commands: null,
    });
    useAppStore.getState().setActiveProject(null);
    expect(localStorage.getItem("active_project_id")).toBeNull();
    expect(localStorage.getItem("active_connection_id")).toBeNull();
    expect(localStorage.getItem("active_session_id")).toBeNull();
  });

  it("setActiveConnection persists ID to localStorage", () => {
    useAppStore.getState().setActiveConnection({
      id: "c2",
      project_id: "p1",
      name: "DB",
      db_type: "postgresql",
      ssh_host: null,
      ssh_port: 22,
      ssh_user: null,
      ssh_key_id: null,
      db_host: "localhost",
      db_port: 5432,
      db_name: "test",
      db_user: null,
      is_read_only: true,
      is_active: true,
      ssh_exec_mode: false,
      ssh_command_template: null,
      ssh_pre_commands: null,
    });
    expect(localStorage.getItem("active_connection_id")).toBe("c2");
  });

  it("setActiveSession persists ID to localStorage", () => {
    useAppStore.getState().setActiveSession({
      id: "s1",
      project_id: "p1",
      title: "Chat",
    });
    expect(localStorage.getItem("active_session_id")).toBe("s1");
  });

  it("updateMessageId replaces a message ID", () => {
    useAppStore.getState().addMessage({
      id: "temp-1",
      role: "user",
      content: "Hello",
      timestamp: Date.now(),
    });
    useAppStore.getState().updateMessageId("temp-1", "real-1");
    expect(useAppStore.getState().messages[0].id).toBe("real-1");
  });

  it("addMessage preserves userRating field", () => {
    useAppStore.getState().addMessage({
      id: "m2",
      role: "assistant",
      content: "Answer",
      userRating: 1,
      timestamp: Date.now(),
    });
    expect(useAppStore.getState().messages[0].userRating).toBe(1);
  });

  it("addMessage preserves rawResult field", () => {
    const rawResult = {
      columns: ["name", "count"],
      rows: [["Alice", 10], ["Bob", 20]],
      total_rows: 2,
    };
    useAppStore.getState().addMessage({
      id: "m3",
      role: "assistant",
      content: "Data",
      rawResult,
      timestamp: Date.now(),
    });
    const msg = useAppStore.getState().messages[0];
    expect(msg.rawResult).toBeDefined();
    expect(msg.rawResult?.columns).toEqual(["name", "count"]);
    expect(msg.rawResult?.rows).toHaveLength(2);
    expect(msg.rawResult?.total_rows).toBe(2);
  });

  it("addMessage works without rawResult", () => {
    useAppStore.getState().addMessage({
      id: "m4",
      role: "assistant",
      content: "No data",
      timestamp: Date.now(),
    });
    expect(useAppStore.getState().messages[0].rawResult).toBeUndefined();
  });
});
