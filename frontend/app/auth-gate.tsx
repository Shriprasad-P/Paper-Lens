"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { loadCurrentUser, loginUser, logoutUser, registerUser, type AuthUser } from "./reader-api";

const stagingAuthRequired = process.env.NEXT_PUBLIC_AUTH_REQUIRED === "true";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(stagingAuthRequired);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!stagingAuthRequired) return;
    void loadCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setChecking(false));
  }, []);

  if (!stagingAuthRequired) return <>{children}</>;
  if (checking) return <main className="reader-loading"><div className="eyebrow">PAPERLENS / STAGING</div><h1>Checking your session…</h1><p>Reconnecting to the local PaperLens API.</p></main>;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const nextUser = mode === "register" ? await registerUser(email.trim(), password) : await loginUser(email.trim(), password);
      setUser(nextUser);
      setPassword("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Authentication could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    setBusy(true);
    setError(null);
    try {
      await logoutUser();
      setUser(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Logout could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  if (!user) {
    return <main className="page-shell auth-shell"><section className="auth-card" aria-labelledby="auth-title"><div className="eyebrow">PAPERLENS / STAGING</div><h1 id="auth-title">{mode === "register" ? "Create your PaperLens account" : "Sign in to PaperLens"}</h1><p className="hero-copy">Your papers, evidence, and research runs stay private to your account.</p><form onSubmit={submit}><label htmlFor="auth-email">Email<input id="auth-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label htmlFor="auth-password">Password<input id="auth-password" type="password" autoComplete={mode === "register" ? "new-password" : "current-password"} minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required /></label><button type="submit" disabled={busy}>{busy ? "Working…" : mode === "register" ? "Create account" : "Sign in"}</button></form>{error ? <div className="status-card error-card" role="alert"><p>{error}</p></div> : null}<button className="auth-mode-button" type="button" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>{mode === "register" ? "Already have an account? Sign in" : "Need an account? Create one"}</button></section></main>;
  }

  return <><div className="auth-toolbar"><span>Signed in as {user.email}</span><button type="button" className="secondary-button" onClick={() => void signOut()} disabled={busy}>Log out</button></div>{error ? <div className="auth-toolbar-error" role="alert">{error}</div> : null}{children}</>;
}
