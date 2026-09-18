import { describe, expect, it } from "vitest";
import { EMPTY_FORM, applyConnectionString } from "@/components/connections/connection-form-helpers";

describe("applyConnectionString", () => {
  it("merges parsed fields and reports the detected type", () => {
    const { form, detected } = applyConnectionString(
      { ...EMPTY_FORM },
      "postgres://alice:s3cret@db.example.com:6543/orders",
    );
    expect(detected).toBe("postgres");
    expect(form.db_type).toBe("postgres");
    expect(form.db_host).toBe("db.example.com");
    expect(form.db_port).toBe("6543");
    expect(form.db_name).toBe("orders");
    expect(form.db_user).toBe("alice");
    expect(form.db_password).toBe("s3cret");
  });

  it("leaves the form untouched and reports null for an unparseable string", () => {
    const original = { ...EMPTY_FORM, db_host: "keep.me" };
    const { form, detected } = applyConnectionString(original, "not a uri");
    expect(detected).toBeNull();
    expect(form.db_host).toBe("keep.me");
  });

  it("does not clobber an existing password when the string omits one", () => {
    const original = { ...EMPTY_FORM, db_password: "existing" };
    const { form } = applyConnectionString(original, "mysql://root@h:3306/shop");
    expect(form.db_password).toBe("existing");
  });
});

describe("C-02: the form ships no exec templates of its own", () => {
  it("exports no presets", async () => {
    const helpers = await import("@/components/connections/connection-form-helpers");
    expect("EXEC_TEMPLATE_PRESETS" in helpers).toBe(false);
  });

  it("refuses a custom command that carries the password", async () => {
    const { commandTemplateError } = await import(
      "@/components/connections/connection-form-helpers"
    );
    // `ps` on the bastion is not private, which is why the server passes the password
    // in the environment instead.
    expect(
      commandTemplateError('mysql -u {db_user} --password "{db_password}" {db_name}'),
    ).toContain("{db_password}");
    expect(commandTemplateError("mysql -h {db_host} -u {db_user} {db_name}")).toBeNull();
    expect(commandTemplateError("   ")).toBeNull();
  });
});

describe("C-15: the form saves what the engine means", () => {
  it("an empty port means THIS engine's port, not PostgreSQL's", async () => {
    const { portForEngine } = await import(
      "@/components/connections/connection-form-helpers"
    );

    // Clearing the port on a MySQL connection used to save 5432 — a failure the form
    // invented, on a field the reader had left blank on purpose.
    expect(portForEngine("", "mysql")).toBe(3306);
    expect(portForEngine("", "mongodb")).toBe(27017);
    expect(portForEngine("", "clickhouse")).toBe(9000);
    expect(portForEngine("", "postgres")).toBe(5432);
    expect(portForEngine("", "something-new")).toBe(5432);
  });

  it("a real port is kept whatever the engine", async () => {
    const { portForEngine } = await import(
      "@/components/connections/connection-form-helpers"
    );

    expect(portForEngine("6543", "postgres")).toBe(6543);
    expect(portForEngine("0", "mysql")).toBe(3306);
    expect(portForEngine("99999", "mysql")).toBe(3306);
  });
});
