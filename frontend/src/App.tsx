import { FormEvent, useState } from "react";

import { requestInference, type InferenceResult } from "./api/inference";
import "./App.css";


function App() {
  const [prompt, setPrompt] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<InferenceResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isLoading) {
      return;
    }

    const cleanPrompt = prompt.trim();
    if (!cleanPrompt) {
      setResult(null);
      setError("Enter a prompt before submitting.");
      return;
    }

    setIsLoading(true);
    setResult(null);
    setError(null);

    try {
      setResult(await requestInference(cleanPrompt));
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The inference request failed.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <section className="workspace" aria-labelledby="page-title">
        <header className="hero">
          <div className="brand-mark" aria-hidden="true">
            RP
          </div>
          <div>
            <p className="eyebrow">Local-first developer tooling</p>
            <h1 id="page-title">RepoPilot</h1>
          </div>
        </header>

        <p className="intro">
          This M0 screen verifies the complete local inference path from your
          browser, through FastAPI, to Gemma 4 running in Ollama.
        </p>

        <form className="prompt-form" onSubmit={handleSubmit} noValidate>
          <label htmlFor="prompt">Prompt</label>
          <textarea
            id="prompt"
            name="prompt"
            rows={7}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Ask the local model something…"
            disabled={isLoading}
            aria-describedby="prompt-help"
          />
          <div className="form-footer">
            <span id="prompt-help">Requests stay on your local machine.</span>
            <button type="submit" disabled={isLoading}>
              {isLoading ? "Generating…" : "Send to Gemma 4"}
            </button>
          </div>
        </form>

        <div className="output" aria-live="polite">
          {isLoading && (
            <div className="status-card loading-state" role="status">
              <span className="spinner" aria-hidden="true" />
              Waiting for the local model…
            </div>
          )}

          {error && (
            <div className="status-card error-state" role="alert">
              <strong>Request failed</strong>
              <p>{error}</p>
            </div>
          )}

          {result && (
            <article className="response-card">
              <div className="response-heading">
                <h2>Generated response</h2>
                <span className="model-tag">{result.model}</span>
              </div>
              <p className="response-text">{result.response}</p>
            </article>
          )}
        </div>
      </section>
    </main>
  );
}

export default App;

