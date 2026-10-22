import { useState } from "react";
import { Layers3 } from "lucide-react";
import { api } from "./api";

export function AuthScreen({ onSignedIn }) {
  const [mode, setMode] = useState("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const signingUp = mode === "signup";

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = signingUp
        ? await api.signUp(email, password, name)
        : await api.logIn(email, password);
      onSignedIn(session);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  function switchTo(next) {
    setMode(next);
    setError("");
  }

  return (
    <main className="auth-screen">
      <form className="auth-card" onSubmit={submit} noValidate={false}>
        <span className="brand-mark large" aria-hidden="true"><Layers3 size={20} /></span>
        <h1>{signingUp ? "Create your workspace" : "Welcome back"}</h1>
        <p className="auth-lead">
          {signingUp
            ? "Upload documents and get answers with sources."
            : "Sign in to your documents and chats."}
        </p>

        {signingUp && (
          <label>
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={120} />
          </label>
        )}
        <label>
          <span>Email</span>
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </label>
        <label>
          <span>Password</span>
          <input
            type="password"
            required
            minLength={signingUp ? 10 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={signingUp ? "new-password" : "current-password"}
          />
          {signingUp && <small>At least 10 characters.</small>}
        </label>

        {error && <div className="auth-error" role="alert">{error}</div>}

        <button className="auth-submit" type="submit" disabled={busy}>
          {busy ? "One moment…" : signingUp ? "Create account" : "Sign in"}
        </button>

        <p className="auth-switch">
          {signingUp ? "Already have an account? " : "New here? "}
          <button type="button" onClick={() => switchTo(signingUp ? "login" : "signup")}>
            {signingUp ? "Sign in" : "Create an account"}
          </button>
        </p>
      </form>
    </main>
  );
}
