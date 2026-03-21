import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Spinner } from "@/components/ui/Spinner";

describe("Spinner", () => {
  it("renders the spinner element", () => {
    const { container } = render(<Spinner />);
    const spinner = container.querySelector(".animate-spin");
    expect(spinner).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(<Spinner className="text-blue-500" />);
    const wrapper = container.firstElementChild;
    expect(wrapper?.className).toContain("text-blue-500");
  });

  it("has correct default styles", () => {
    const { container } = render(<Spinner />);
    const wrapper = container.firstElementChild;
    expect(wrapper?.className).toContain("flex");
    expect(wrapper?.className).toContain("justify-center");
  });
});
