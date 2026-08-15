import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
    /**
     * Cap the worker pool. Vitest defaults to one worker per core, and on a
     * 14-core machine that made this suite — 90 files, each paying for its own
     * jsdom — thrash badly enough that tests failed the 5000 ms ceiling while
     * doing nothing wrong.
     *
     * Measured 2026-08-16, three full runs per setting:
     *
     *   default (14):  650 passed / 19 failed / 21 failed   ~72 s
     *   maxWorkers 4:  650 passed / 650 passed              ~27 s
     *   maxWorkers 6:  650 passed / 650 passed              ~21 s
     *   maxWorkers 50%: 650 / 650 / 650                     ~15 s
     *
     * A gate that fails two runs in three is not a gate, and every "suite
     * green" reported against it was one sample of a coin flip. A percentage
     * rather than a number because CI runners have two to four cores, where a
     * fixed 6 would over-subscribe exactly the way 14 does here.
     */
    maxWorkers: "50%",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});
