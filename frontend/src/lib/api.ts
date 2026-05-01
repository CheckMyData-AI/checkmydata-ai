// Re-export shim. All types and API namespaces now live under `./api/`.
// Kept to preserve the ``@/lib/api`` import path used across the codebase (T28).
export * from "./api/index";
export { api as default } from "./api/index";
