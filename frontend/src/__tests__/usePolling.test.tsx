import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePolling } from "@/hooks/usePolling";

function PollingProbe({
  spy,
  interval,
  enabled,
  leading,
  pauseWhenHidden,
  maxDurationMs,
}: {
  spy: () => void;
  interval: number;
  enabled?: boolean;
  leading?: boolean;
  pauseWhenHidden?: boolean;
  maxDurationMs?: number;
}) {
  usePolling(spy, interval, [], {
    enabled,
    leading,
    pauseWhenHidden,
    maxDurationMs,
  });
  return null;
}

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("invokes callback on each interval", () => {
    const spy = vi.fn();
    render(<PollingProbe spy={spy} interval={1000} pauseWhenHidden={false} />);

    expect(spy).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(spy).toHaveBeenCalledTimes(3);
  });

  it("supports leading invocation", () => {
    const spy = vi.fn();
    render(
      <PollingProbe spy={spy} interval={1000} leading pauseWhenHidden={false} />,
    );

    expect(spy).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(spy).toHaveBeenCalledTimes(3);
  });

  it("does nothing when disabled", () => {
    const spy = vi.fn();
    render(
      <PollingProbe
        spy={spy}
        interval={1000}
        enabled={false}
        pauseWhenHidden={false}
      />,
    );

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(spy).not.toHaveBeenCalled();
  });

  it("stops polling after maxDurationMs", () => {
    const spy = vi.fn();
    render(
      <PollingProbe
        spy={spy}
        interval={1000}
        pauseWhenHidden={false}
        maxDurationMs={2500}
      />,
    );

    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("cleans up on unmount", () => {
    const spy = vi.fn();
    const { unmount } = render(
      <PollingProbe spy={spy} interval={1000} pauseWhenHidden={false} />,
    );

    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(spy).toHaveBeenCalledTimes(1);

    unmount();

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("swallows callback errors so polling continues", () => {
    let calls = 0;
    const spy = vi.fn(() => {
      calls += 1;
      if (calls === 1) {
        throw new Error("boom");
      }
    });

    render(<PollingProbe spy={spy} interval={1000} pauseWhenHidden={false} />);

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(spy).toHaveBeenCalledTimes(3);
  });
});
