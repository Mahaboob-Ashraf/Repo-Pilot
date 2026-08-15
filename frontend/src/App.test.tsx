import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { requestInference } from "./api/inference";


vi.mock("./api/inference", () => ({
  requestInference: vi.fn(),
}));

const mockedRequestInference = vi.mocked(requestInference);

describe("RepoPilot M0 inference screen", () => {
  beforeEach(() => {
    mockedRequestInference.mockReset();
  });

  it("renders the initial prompt form", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "RepoPilot" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Prompt" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Send to Gemma 4" }),
    ).toBeEnabled();
  });

  it("does not submit a blank prompt", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "   ");
    await user.click(screen.getByRole("button", { name: "Send to Gemma 4" }));

    expect(mockedRequestInference).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter a prompt before submitting.",
    );
  });

  it("displays a successful API response and model", async () => {
    mockedRequestInference.mockResolvedValue({
      model: "gemma4:e4b-it-qat",
      response: "The local path is working.",
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(
      screen.getByRole("textbox", { name: "Prompt" }),
      "Check the local path",
    );
    await user.click(screen.getByRole("button", { name: "Send to Gemma 4" }));

    expect(await screen.findByText("The local path is working.")).toBeVisible();
    expect(screen.getByText("gemma4:e4b-it-qat")).toBeVisible();
    expect(mockedRequestInference).toHaveBeenCalledWith("Check the local path");
  });

  it("shows a readable error when the API call fails", async () => {
    mockedRequestInference.mockRejectedValue(
      new Error("Could not reach the RepoPilot backend."),
    );
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("textbox", { name: "Prompt" }), "Hello");
    await user.click(screen.getByRole("button", { name: "Send to Gemma 4" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach the RepoPilot backend.",
    );
    expect(
      screen.getByRole("button", { name: "Send to Gemma 4" }),
    ).toBeEnabled();
  });
});

