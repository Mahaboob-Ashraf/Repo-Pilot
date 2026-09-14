import { useEffect, useState } from "react";

type Theme = "dark" | "light" | "system";
const storageKey = "repopilot-theme";

function readTheme(): Theme {
  try {
    const value = localStorage.getItem(storageKey);
    if (value === "system" || value === "light") return value;
  } catch { /* Theme persistence is optional. */ }
  return "dark";
}

export function ThemeSelector() {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme = theme === "system"
        ? (media.matches ? "dark" : "light")
        : theme;
    };
    apply();
    try { localStorage.setItem(storageKey, theme); } catch { /* Optional persistence. */ }
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  return <fieldset className="theme-control">
    <legend className="sr-only">Theme</legend>
    <div className="theme-options" role="group" aria-label="Theme">
      {(["system", "light", "dark"] as const).map((option) => (
        <button
          key={option}
          type="button"
          className="theme-option"
          aria-pressed={theme === option}
          onClick={() => setTheme(option)}
        >
          <span className={`theme-glyph theme-${option}`} aria-hidden="true" />
          {option[0].toUpperCase() + option.slice(1)}
        </button>
      ))}
    </div>
  </fieldset>;
}
