import { describe, it, expect, beforeEach } from "vitest";
import { useAppStore } from "@/stores/app-store";

beforeEach(() => {
  useAppStore.setState({
    projects: [],
    activeProject: null,
    connections: [],
    activeConnection: null,
    chatSessions: [],
    activeChatSession: null,
    messages: [],
  });
});

describe("app store", () => {
  it("setActiveProject updates state", () => {
    const project = {
      id: "p1",
      name: "Test",
      description: "",
      repo_url: null,
      repo_branch: "main",
      ssh_key_id: null,
      default_llm_provider: null,
      default_llm_model: null,
    };

    useAppStore.getState().setActiveProject(project);
    expect(useAppStore.getState().activeProject?.id).toBe("p1");
  });

  it("addMessage appends to messages", () => {
    useAppStore.getState().addMessage({
      id: "m1",
      role: "user",
      content: "Hello",
    });
    expect(useAppStore.getState().messages).toHaveLength(1);
    expect(useAppStore.getState().messages[0].content).toBe("Hello");
  });
});
