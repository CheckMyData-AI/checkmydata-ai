import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { APP_PANELS } from "@/hooks/useAppPanel";

/**
 * A declared panel must render itself, not something else.
 *
 * `APP_PANELS` is the allow-list `useAppPanel` validates `?panel=` against, so every
 * name in it is a URL a user can reach and a link the product can hand out. But the
 * switch that turns a panel into a component ended with an unconditional `ChatPanel`
 * fallback, and two declared names — `knowledge` and `insights` — had no case above
 * it. Both rendered the chat, silently, for as long as they had existed.
 *
 * That is worse than a 404: a route that does not exist teaches the user immediately,
 * and one that renders a plausible other screen does not teach them at all.
 *
 * A source check rather than a render test on purpose. Mounting the page needs the
 * router, six stores and the streaming client, and the defect is not in any of them —
 * it is the absence of a branch. This asks the one question that was unasked.
 */

const PAGE = resolve(__dirname, "../app/app/page.tsx");

describe("every declared app panel has a destination", () => {
  const source = readFileSync(PAGE, "utf8");
  const render = source.slice(source.indexOf("const renderCenterPanel"));
  const body = render.slice(0, render.indexOf("\n  };"));

  it.each(APP_PANELS.filter((p) => p !== "chat"))(
    "`?panel=%s` is handled explicitly",
    (panel) => {
      expect(body).toContain(`effectivePanel === "${panel}"`);
    },
  );

  it("chat is the fallback, and is therefore the only one that needs no case", () => {
    expect(body).toContain("<ChatPanel />");
  });

  it("the fallback is last, so no case is unreachable behind it", () => {
    const fallback = body.lastIndexOf("<ChatPanel />");
    for (const panel of APP_PANELS.filter((p) => p !== "chat")) {
      expect(body.indexOf(`effectivePanel === "${panel}"`)).toBeLessThan(fallback);
    }
  });
});

/**
 * The switch was the second gate, not the first.
 *
 * `effectivePanel` resolved the URL through its own enumeration of five names while
 * `APP_PANELS` held eight, so three panels were rejected before the switch ever saw
 * them — the checks above would have passed while the routes still went nowhere.
 * TypeScript found it (the new cases compared against an already-narrowed union);
 * this keeps it found, because the next panel added would reintroduce it silently.
 */
describe("the panel resolver does not keep its own second list", () => {
  const source = readFileSync(PAGE, "utf8");
  const memo = source.slice(
    source.indexOf("const effectivePanel"),
    source.indexOf("}, [panel,"),
  );

  it.each(APP_PANELS)("does not re-decide `%s` by name", (panel) => {
    expect(memo).not.toContain(`panel === "${panel}"`);
  });

  it("passes a declared panel through instead", () => {
    expect(memo).toContain("if (panel) return panel;");
  });
});
