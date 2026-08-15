export interface InferenceResult {
  model: string;
  response: string;
}

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

function apiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
    /\/$/,
    "",
  );
}

function errorDetail(payload: unknown): string | null {
  if (
    typeof payload === "object" &&
    payload !== null &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return null;
}

export async function requestInference(prompt: string): Promise<InferenceResult> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}/api/inference`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
  } catch {
    throw new Error("Could not reach the RepoPilot backend.");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The backend returned an unreadable response.");
  }

  if (!response.ok) {
    throw new Error(errorDetail(payload) || "The inference request failed.");
  }

  if (
    typeof payload !== "object" ||
    payload === null ||
    !("model" in payload) ||
    typeof payload.model !== "string" ||
    !("response" in payload) ||
    typeof payload.response !== "string"
  ) {
    throw new Error("The backend returned an unexpected response.");
  }

  return { model: payload.model, response: payload.response };
}

