/**
 * T05b — the edit form sends what the user changed, nothing else.
 * `docs/audits/2026-09-23-recent-work-audit.md` §3.2 (F-C1, F-C2, F-C9).
 */
import { describe, expect, it } from "vitest";
import {
  EMPTY_FORM,
  buildConnectionUpdates,
  changedFields,
  editPatch,
} from "@/components/connections/connection-form-helpers";

function patchOf(r: ReturnType<typeof editPatch>): Record<string, unknown> {
  if (!r.ok) throw new Error(r.error);
  return r.patch;
}

const stored = {
  ...EMPTY_FORM,
  name: "prod",
  db_type: "mysql",
  db_host: "10.0.0.5",
  db_port: "3306",
  db_name: "shop",
  db_user: "reader",
  ssh_host: "bastion",
  ssh_user: "deploy",
  ssh_key_id: "someone-elses-key",
  ssh_command_template: "legacy {db_password} template",
};

describe("editPatch", () => {
  it("a rename sends the name and nothing the backend would re-verify or refuse", () => {
    const patch = patchOf(editPatch({ ...stored, name: "prod-eu" }, stored, { useConnString: false, isMCP: false }));
    expect(patch).toEqual({ name: "prod-eu" });
    expect(patch).not.toHaveProperty("ssh_key_id"); // F-C1
    expect(patch).not.toHaveProperty("ssh_command_template"); // F-C2
    expect(patch).not.toHaveProperty("connection_string"); // F-C9: the DSN survives
  });

  it("an untouched MCP connection keeps its args and environment", () => {
    const mcp = { ...EMPTY_FORM, name: "tools", db_type: "mcp", mcp_server_command: "npx x" };
    const patch = patchOf(editPatch({ ...mcp, name: "tools-2" }, mcp, { useConnString: false, isMCP: true }));
    expect(patch).not.toHaveProperty("mcp_env");
    expect(patch).not.toHaveProperty("mcp_server_args");
  });

  it("changing the host moves the connection onto its fields, dropping any DSN", () => {
    const patch = patchOf(editPatch({ ...stored, db_host: "10.0.0.6" }, stored, { useConnString: false, isMCP: false }));
    expect(patch).toMatchObject({ db_host: "10.0.0.6", connection_string: null });
  });

  it("a typed password and a new DSN are always sent", () => {
    expect(patchOf(editPatch({ ...stored, db_password: "s3cret" }, stored, { useConnString: false, isMCP: false }))).toEqual({
      db_password: "s3cret",
    });
    const dsn = patchOf(editPatch({ ...stored, connection_string: "mysql://u@h/db" }, stored, {
      useConnString: true,
      isMCP: false,
    }));
    expect(dsn).toMatchObject({ connection_string: "mysql://u@h/db" });
  });

  it("nothing changed means an empty patch", () => {
    expect(patchOf(editPatch({ ...stored }, stored, { useConnString: false, isMCP: false }))).toEqual({});
  });

  it("an invalid MCP env is an error, not a patch", () => {
    const mcp = { ...EMPTY_FORM, db_type: "mcp" };
    const r = editPatch({ ...mcp, mcp_env: "{nope" }, mcp, { useConnString: false, isMCP: true });
    expect(r.ok).toBe(false);
  });
});

describe("changedFields", () => {
  it("compares by value, arrays included", () => {
    expect(changedFields({ a: ["x"], b: 1 }, { a: ["x"], b: 2 })).toEqual({ b: 1 });
    expect(buildConnectionUpdates(stored, { useConnString: false, isMCP: false }).updates).toBeDefined();
  });
});

describe("commandTemplateError — $DBPASS (F-C2)", () => {
  it("refuses the password as an argument and accepts it as an environment assignment", async () => {
    const { commandTemplateError } = await import("@/components/connections/connection-form-helpers");
    expect(commandTemplateError('mysql -p"$DBPASS" {db_name}')).toMatch(/environment variable/);
    expect(commandTemplateError("mysql --password=$DBPASS {db_name}")).not.toBeNull();
    expect(commandTemplateError('MYSQL_PWD="$DBPASS" mysql {db_name}')).toBeNull();
    expect(commandTemplateError('CLICKHOUSE_PASSWORD="${DBPASS}" clickhouse-client')).toBeNull();
  });
});
