"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api, type Connection, type Project } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";

const TOTAL_STEPS = 5;

const DEFAULT_PORTS: Record<string, string> = {
  postgres: "5432",
  mysql: "3306",
  clickhouse: "9000",
  mongodb: "27017",
};

const DB_TYPE_LABELS: Record<string, string> = {
  postgres: "PostgreSQL",
  mysql: "MySQL",
  clickhouse: "ClickHouse",
  mongodb: "MongoDB",
};

const inputCls =
  "w-full bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors";

const btnPrimary =
  "px-5 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed";

const btnSecondary =
  "px-5 py-2 rounded-lg bg-surface-2 hover:bg-surface-3 text-text-secondary text-sm font-medium transition-colors border border-border-subtle";

interface OnboardingWizardProps {
  onComplete: () => void;
}

export function OnboardingWizard({ onComplete }: OnboardingWizardProps) {
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState<"forward" | "back">("forward");

  const [dbType, setDbType] = useState("postgres");
  const [host, setHost] = useState("127.0.0.1");
  const [port, setPort] = useState("5432");
  const [dbName, setDbName] = useState("");
  const [dbUser, setDbUser] = useState("");
  const [dbPassword, setDbPassword] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [sshHost, setSshHost] = useState("");
  const [sshPort, setSshPort] = useState("22");
  const [sshUser, setSshUser] = useState("");
  const [sshKeyId, setSshKeyId] = useState("");

  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "success" | "error">("idle");
  const [testError, setTestError] = useState("");

  const [indexStatus, setIndexStatus] = useState<"idle" | "indexing" | "done" | "error">("idle");

  const [repoUrl, setRepoUrl] = useState("");

  const [question, setQuestion] = useState("Show me the top 10 users by total order amount");

  const [createdProject, setCreatedProject] = useState<Project | null>(null);
  const [createdConnection, setCreatedConnection] = useState<Connection | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const sshKeys = useAppStore((s) => s.sshKeys);
  const setProjects = useAppStore((s) => s.setProjects);
  const setActiveProject = useAppStore((s) => s.setActiveProject);
  const setConnections = useAppStore((s) => s.setConnections);
  const setActiveConnection = useAppStore((s) => s.setActiveConnection);
  const user = useAuthStore((s) => s.user);

  const autoAdvanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (autoAdvanceTimer.current) clearTimeout(autoAdvanceTimer.current);
    };
  }, []);

  const goNext = useCallback(() => {
    setDirection("forward");
    setStep((s) => Math.min(s + 1, TOTAL_STEPS - 1));
  }, []);

  const goBack = useCallback(() => {
    setDirection("back");
    setStep((s) => Math.max(s - 1, 0));
  }, []);

  const handleDbTypeChange = (type: string) => {
    setDbType(type);
    setPort(DEFAULT_PORTS[type] || "5432");
  };

  const handleCreateConnection = async () => {
    setIsSubmitting(true);
    try {
      let project = createdProject;
      if (!project) {
        project = await api.projects.create({ name: dbName || "My Project", description: "" });
        setCreatedProject(project);
      }

      const payload: Record<string, unknown> = {
        project_id: project.id,
        name: dbName || `${DB_TYPE_LABELS[dbType]} connection`,
        db_type: dbType,
        db_host: host,
        db_port: parseInt(port, 10) || parseInt(DEFAULT_PORTS[dbType], 10),
        db_name: dbName,
        db_user: dbUser,
        db_password: dbPassword,
        is_read_only: true,
      };

      if (showAdvanced && sshHost) {
        payload.ssh_host = sshHost;
        payload.ssh_port = parseInt(sshPort, 10) || 22;
        payload.ssh_user = sshUser;
        if (sshKeyId) payload.ssh_key_id = sshKeyId;
      }

      const conn = await api.connections.create(payload);
      setCreatedConnection(conn);
      goNext();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to create connection", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTestConnection = useCallback(async () => {
    if (!createdConnection) return;
    setTestStatus("testing");
    setTestError("");
    try {
      const result = await api.connections.test(createdConnection.id);
      if (result.success) {
        setTestStatus("success");
        autoAdvanceTimer.current = setTimeout(() => goNext(), 1500);
      } else {
        setTestStatus("error");
        setTestError(result.error || "Connection test failed");
      }
    } catch (err) {
      setTestStatus("error");
      setTestError(err instanceof Error ? err.message : "Connection test failed");
    }
  }, [createdConnection, goNext]);

  useEffect(() => {
    if (step === 1 && createdConnection && testStatus === "idle") {
      handleTestConnection();
    }
  }, [step, createdConnection, testStatus, handleTestConnection]);

  const handleIndexDb = async () => {
    if (!createdConnection) return;
    setIndexStatus("indexing");
    try {
      await api.connections.indexDb(createdConnection.id);
      setIndexStatus("done");
    } catch {
      setIndexStatus("error");
    }
  };

  const handleComplete = async () => {
    setIsSubmitting(true);
    try {
      await api.auth.completeOnboarding();
      const fresh = await api.auth.me();
      useAuthStore.setState({ user: fresh });
      try { localStorage.setItem("auth_user", JSON.stringify(fresh)); } catch { /* */ }

      if (createdProject) {
        const projects = await api.projects.list();
        setProjects(projects);
        setActiveProject(createdProject);
        if (createdConnection) {
          const conns = await api.connections.listByProject(createdProject.id);
          setConnections(conns);
          setActiveConnection(createdConnection);
        }
      }

      onComplete();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to complete onboarding", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSkipAll = async () => {
    setIsSubmitting(true);
    try {
      await api.auth.completeOnboarding();
      const fresh = await api.auth.me();
      useAuthStore.setState({ user: fresh });
      try { localStorage.setItem("auth_user", JSON.stringify(fresh)); } catch { /* */ }
      onComplete();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to skip onboarding", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDemoSetup = async () => {
    setIsSubmitting(true);
    try {
      const result = await api.demo.setup();
      await api.auth.completeOnboarding();
      const fresh = await api.auth.me();
      useAuthStore.setState({ user: fresh });
      try { localStorage.setItem("auth_user", JSON.stringify(fresh)); } catch { /* */ }

      const projects = await api.projects.list();
      setProjects(projects);
      const demoProject = projects.find((p) => p.id === result.project_id);
      if (demoProject) {
        setActiveProject(demoProject);
        const conns = await api.connections.listByProject(demoProject.id);
        setConnections(conns);
        const demoConn = conns.find((c) => c.id === result.connection_id);
        if (demoConn) setActiveConnection(demoConn);
      }

      onComplete();
      toast("Demo project created", "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to set up demo", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const stepTitles = [
    "Connect your database",
    "Test connection",
    "Index your database",
    "Connect your code",
    "Ask your first question",
  ];

  const renderStep = () => {
    switch (step) {
      case 0:
        return (
          <div className="space-y-4">
            <p className="text-sm text-text-secondary">
              Connect your first database to start querying it with natural language.
            </p>

            <div>
              <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                Database type
              </label>
              <div className="grid grid-cols-4 gap-2">
                {Object.entries(DB_TYPE_LABELS).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => handleDbTypeChange(key)}
                    className={`px-3 py-2 rounded-lg text-xs font-medium transition-all border ${
                      dbType === key
                        ? "bg-accent-muted border-accent text-accent"
                        : "bg-surface-1 border-border-subtle text-text-secondary hover:border-border-default"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-xs font-medium text-text-tertiary mb-1.5">Host</label>
                <input
                  className={inputCls}
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  placeholder="127.0.0.1"
                  maxLength={255}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-text-tertiary mb-1.5">Port</label>
                <input
                  className={inputCls}
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  placeholder={DEFAULT_PORTS[dbType]}
                  maxLength={5}
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                Database name
              </label>
              <input
                className={inputCls}
                value={dbName}
                onChange={(e) => setDbName(e.target.value)}
                placeholder="my_database"
                maxLength={128}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                  Username
                </label>
                <input
                  className={inputCls}
                  value={dbUser}
                  onChange={(e) => setDbUser(e.target.value)}
                  placeholder="postgres"
                  maxLength={128}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                  Password
                </label>
                <input
                  className={inputCls}
                  type="password"
                  value={dbPassword}
                  onChange={(e) => setDbPassword(e.target.value)}
                  placeholder="********"
                  maxLength={255}
                />
              </div>
            </div>

            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1.5 text-xs text-text-tertiary hover:text-text-secondary transition-colors"
            >
              <Icon
                name={showAdvanced ? "chevron-down" : "chevron-right"}
                size={12}
              />
              SSH Tunnel (Advanced)
            </button>

            {showAdvanced && (
              <div className="space-y-3 pl-2 border-l-2 border-border-subtle">
                <div className="grid grid-cols-3 gap-3">
                  <div className="col-span-2">
                    <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                      SSH Host
                    </label>
                    <input
                      className={inputCls}
                      value={sshHost}
                      onChange={(e) => setSshHost(e.target.value)}
                      placeholder="ssh.example.com"
                      maxLength={255}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                      SSH Port
                    </label>
                    <input
                      className={inputCls}
                      value={sshPort}
                      onChange={(e) => setSshPort(e.target.value)}
                      placeholder="22"
                      maxLength={5}
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                    SSH User
                  </label>
                  <input
                    className={inputCls}
                    value={sshUser}
                    onChange={(e) => setSshUser(e.target.value)}
                    placeholder="ubuntu"
                    maxLength={128}
                  />
                </div>
                {sshKeys.length > 0 && (
                  <div>
                    <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                      SSH Key
                    </label>
                    <select
                      className={inputCls}
                      value={sshKeyId}
                      onChange={(e) => setSshKeyId(e.target.value)}
                    >
                      <option value="">None</option>
                      {sshKeys.map((k) => (
                        <option key={k.id} value={k.id}>
                          {k.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            )}
          </div>
        );

      case 1:
        return (
          <div className="flex flex-col items-center justify-center py-8 space-y-4">
            {testStatus === "testing" && (
              <>
                <div className="w-12 h-12 rounded-full border-2 border-accent border-t-transparent animate-spin" />
                <p className="text-sm text-text-secondary">Testing connection...</p>
              </>
            )}
            {testStatus === "success" && (
              <>
                <div className="w-12 h-12 rounded-full bg-success/20 flex items-center justify-center">
                  <Icon name="check" size={24} className="text-success" />
                </div>
                <p className="text-sm text-success font-medium">Connection successful</p>
              </>
            )}
            {testStatus === "error" && (
              <>
                <div className="w-12 h-12 rounded-full bg-error/20 flex items-center justify-center">
                  <Icon name="x" size={24} className="text-error" />
                </div>
                <p className="text-sm text-error font-medium">Connection failed</p>
                {testError && (
                  <p className="text-xs text-text-muted max-w-sm text-center">{testError}</p>
                )}
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => {
                      setTestStatus("idle");
                      goBack();
                    }}
                    className={btnSecondary}
                  >
                    Edit connection
                  </button>
                  <button
                    onClick={() => {
                      setTestStatus("idle");
                      handleTestConnection();
                    }}
                    className={btnPrimary}
                  >
                    Retry
                  </button>
                </div>
              </>
            )}
          </div>
        );

      case 2:
        return (
          <div className="flex flex-col items-center justify-center py-8 space-y-4">
            <p className="text-sm text-text-secondary text-center max-w-sm">
              Indexing analyzes your database schema so the AI understands your tables,
              relationships, and data patterns.
            </p>

            {indexStatus === "idle" && (
              <button onClick={handleIndexDb} className={btnPrimary}>
                Start indexing
              </button>
            )}
            {indexStatus === "indexing" && (
              <>
                <div className="w-12 h-12 rounded-full border-2 border-accent border-t-transparent animate-spin" />
                <p className="text-sm text-text-secondary">Indexing your database...</p>
                <p className="text-xs text-text-muted">This may take a minute</p>
              </>
            )}
            {indexStatus === "done" && (
              <>
                <div className="w-12 h-12 rounded-full bg-success/20 flex items-center justify-center">
                  <Icon name="check" size={24} className="text-success" />
                </div>
                <p className="text-sm text-success font-medium">Indexing complete</p>
              </>
            )}
            {indexStatus === "error" && (
              <>
                <div className="w-12 h-12 rounded-full bg-warning/20 flex items-center justify-center">
                  <Icon name="x" size={24} className="text-warning" />
                </div>
                <p className="text-sm text-warning font-medium">
                  Indexing had issues, but you can still use the app
                </p>
                <button onClick={goNext} className={btnPrimary}>
                  Continue
                </button>
              </>
            )}
          </div>
        );

      case 3:
        return (
          <div className="space-y-4">
            <p className="text-sm text-text-secondary">
              Connect a Git repository so the AI can understand your application code and how it
              interacts with the database. This step is optional.
            </p>
            <div>
              <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                Git repository URL
              </label>
              <input
                className={inputCls}
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="git@github.com:org/repo.git"
                maxLength={500}
              />
            </div>
            {sshKeys.length > 0 && (
              <div>
                <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                  SSH Key for repo access
                </label>
                <select
                  className={inputCls}
                  value={sshKeyId}
                  onChange={(e) => setSshKeyId(e.target.value)}
                >
                  <option value="">None</option>
                  {sshKeys.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        );

      case 4:
        return (
          <div className="space-y-4">
            <p className="text-sm text-text-secondary">
              Try asking a question about your database. The AI will generate SQL and return
              results.
            </p>
            <div>
              <label className="block text-xs font-medium text-text-tertiary mb-1.5">
                Your question
              </label>
              <textarea
                className={`${inputCls} min-h-[80px] resize-none font-['DM_Sans']`}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g. Show me revenue by month"
                maxLength={2000}
              />
            </div>
            <p className="text-xs text-text-muted">
              You can always change this later in the chat panel.
            </p>
          </div>
        );

      default:
        return null;
    }
  };

  const canProceed = () => {
    switch (step) {
      case 0:
        return host.trim() && dbName.trim();
      case 1:
        return testStatus === "success";
      case 2:
        return true;
      case 3:
        return true;
      case 4:
        return true;
      default:
        return false;
    }
  };

  const handleNext = () => {
    if (step === 0) {
      handleCreateConnection();
      return;
    }
    if (step === 3 && repoUrl.trim() && createdProject) {
      api.projects
        .update(createdProject.id, {
          repo_url: repoUrl,
          ssh_key_id: sshKeyId || null,
        })
        .catch(() => toast("Failed to save repository settings", "error"));
    }
    if (step === TOTAL_STEPS - 1) {
      handleComplete();
      return;
    }
    goNext();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg mx-4 bg-surface-1 rounded-2xl border border-border-subtle shadow-2xl overflow-hidden">
        <div className="px-6 pt-6 pb-4">
          <div className="flex items-center justify-center gap-2 mb-6">
            {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
              <div
                key={i}
                className={`h-1.5 rounded-full transition-all duration-300 ${
                  i === step
                    ? "w-8 bg-accent"
                    : i < step
                      ? "w-4 bg-accent/50"
                      : "w-4 bg-surface-3"
                }`}
              />
            ))}
          </div>

          <div className="flex items-center gap-3 mb-1">
            <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center">
              <span className="text-sm font-semibold text-accent">{step + 1}</span>
            </div>
            <h2 className="text-lg font-semibold text-text-primary">
              {stepTitles[step]}
            </h2>
            {step === 3 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-surface-3 text-text-muted">
                Optional
              </span>
            )}
          </div>
        </div>

        <div
          className={`px-6 max-h-[50vh] overflow-y-auto ${
            direction === "forward" ? "animate-onboarding-forward" : "animate-onboarding-back"
          }`}
          key={step}
        >
          {renderStep()}
        </div>

        <div className="px-6 py-4 flex items-center justify-between border-t border-border-subtle mt-4">
          <div>
            {step > 0 ? (
              <button onClick={goBack} className={btnSecondary}>
                Back
              </button>
            ) : (
              <button
                onClick={handleDemoSetup}
                disabled={isSubmitting}
                className="px-4 py-2 rounded-lg text-sm text-accent hover:text-accent-hover hover:bg-accent-muted transition-colors disabled:opacity-40"
              >
                Try demo instead
              </button>
            )}
          </div>

          <div className="flex items-center gap-3">
            {step === 3 && (
              <button onClick={goNext} className={btnSecondary}>
                Skip
              </button>
            )}
            {step === 2 && indexStatus === "idle" && (
              <button onClick={goNext} className={btnSecondary}>
                Skip
              </button>
            )}
            {step !== 1 && (
              <button
                onClick={handleNext}
                disabled={!canProceed() || isSubmitting}
                className={btnPrimary}
              >
                {isSubmitting
                  ? "..."
                  : step === TOTAL_STEPS - 1
                    ? "Finish setup"
                    : "Continue"}
              </button>
            )}
          </div>
        </div>

        <div className="px-6 pb-4 flex justify-center">
          <button
            onClick={handleSkipAll}
            disabled={isSubmitting}
            className="text-xs text-text-muted hover:text-text-secondary transition-colors"
          >
            Skip setup entirely
          </button>
        </div>
      </div>
    </div>
  );
}
