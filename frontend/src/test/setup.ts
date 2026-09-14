import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, "matchMedia", { writable: true, value: vi.fn((query: string) => ({
    matches: query.includes("min-width"), media: query, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })) });
});
// jsdom lacks native dialog behavior; real focus trapping is reviewed in-browser.
HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); this.querySelector<HTMLButtonElement>("button")?.focus(); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };


afterEach(() => {
  cleanup();
});
