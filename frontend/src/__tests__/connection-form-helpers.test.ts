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
