import { describe, expect, it } from "vitest";
import { parseConnectionString } from "@/lib/connection-string";

describe("parseConnectionString", () => {
  it("parses a full postgres URI", () => {
    expect(parseConnectionString("postgres://alice:s3cret@db.example.com:6543/orders")).toEqual({
      db_type: "postgres",
      db_host: "db.example.com",
      db_port: "6543",
      db_name: "orders",
      db_user: "alice",
      db_password: "s3cret",
    });
  });

  it("maps postgresql:// scheme and defaults the port", () => {
    const r = parseConnectionString("postgresql://bob@localhost/app");
    expect(r?.db_type).toBe("postgres");
    expect(r?.db_port).toBe("5432");
    expect(r?.db_user).toBe("bob");
    expect(r?.db_name).toBe("app");
  });

  it("parses mysql and defaults port 3306", () => {
    const r = parseConnectionString("mysql://root:pw@10.0.0.5/shop");
    expect(r?.db_type).toBe("mysql");
    expect(r?.db_port).toBe("3306");
    expect(r?.db_host).toBe("10.0.0.5");
  });

  it("maps mongodb+srv to mongodb", () => {
    const r = parseConnectionString("mongodb+srv://u:p@cluster0.abcd.mongodb.net/analytics");
    expect(r?.db_type).toBe("mongodb");
    expect(r?.db_host).toBe("cluster0.abcd.mongodb.net");
    expect(r?.db_name).toBe("analytics");
  });

  it("maps clickhouse and tcp schemes", () => {
    expect(parseConnectionString("clickhouse://u:p@ch.host:9000/metrics")?.db_type).toBe("clickhouse");
    expect(parseConnectionString("tcp://u:p@ch.host:9000/metrics")?.db_type).toBe("clickhouse");
  });

  it("url-decodes credentials", () => {
    const r = parseConnectionString("postgres://user%40corp:p%40ss@h:5432/db");
    expect(r?.db_user).toBe("user@corp");
    expect(r?.db_password).toBe("p@ss");
  });

  it("returns null for unknown schemes or non-URIs", () => {
    expect(parseConnectionString("redis://h:6379")).toBeNull();
    expect(parseConnectionString("just some text")).toBeNull();
    expect(parseConnectionString("")).toBeNull();
  });
});
