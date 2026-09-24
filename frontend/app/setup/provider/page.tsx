"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { saveProviderConfig, testProviderConfig, type ProviderConfig } from "../../reader-api";

export default function ProviderSetupPage() {
  const router = useRouter();
  const [kind, setKind] = useState<ProviderConfig["provider_type"]>("ollama");
  const [name, setName] = useState("Local Ollama");
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:11434");
  const [generationModel, setGenerationModel] = useState("qwen3:4b");
  const [embeddingModel, setEmbeddingModel] = useState("nomic-embed-text");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function selectKind(next: ProviderConfig["provider_type"]) {
    setKind(next);
    if (next === "ollama") {
      setName("Local Ollama"); setBaseUrl("http://127.0.0.1:11434"); setGenerationModel("qwen3:4b"); setEmbeddingModel("nomic-embed-text");
    } else if (next === "mlx") {
      setName("Local MLX"); setBaseUrl("http://127.0.0.1:8080/v1"); setGenerationModel("local-model"); setEmbeddingModel("");
    } else if (next === "openai") {
      setName("OpenAI"); setBaseUrl("https://api.openai.com/v1"); setGenerationModel("gpt-4o-mini"); setEmbeddingModel("text-embedding-3-small");
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null); setMessage(null);
    try {
      const config = await saveProviderConfig({ provider_type: kind, display_name: name.trim(), base_url: baseUrl.trim(), generation_model: generationModel.trim(), embedding_model: embeddingModel.trim() || null, api_key: apiKey || null });
      setApiKey("");
      try {
        const result = await testProviderConfig(config.id);
        setMessage(result.message);
        router.replace("/library");
      } catch (testError) {
        setError(testError instanceof Error ? `Saved, but the connection test needs attention: ${testError.message}` : "Saved, but the connection test failed. Start the provider and test again.");
      }
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Provider configuration could not be saved."); }
    finally { setBusy(false); }
  }

  return <main className="page-shell auth-shell"><section className="auth-card provider-setup-card" aria-labelledby="provider-title"><div className="eyebrow">PAPERLENS / ONBOARDING</div><h1 id="provider-title">Choose your AI provider</h1><p className="hero-copy">PaperLens keeps provider settings tied to your account. Local Ollama stays on this device and uses Metal when available, with CPU fallback. MLX is available for Apple-silicon model servers.</p><div className="provider-choice"><button type="button" className={kind === "ollama" ? "selected" : ""} onClick={() => selectKind("ollama")}>Ollama<span>Metal or CPU fallback</span></button><button type="button" className={kind === "mlx" ? "selected" : ""} onClick={() => selectKind("mlx")}>MLX local<span>OpenAI-compatible server</span></button><button type="button" className={kind !== "ollama" && kind !== "mlx" ? "selected" : ""} onClick={() => selectKind("openai")}>Cloud provider<span>OpenAI-compatible endpoint</span></button></div><form onSubmit={submit}><label htmlFor="provider-name">Configuration name<input id="provider-name" value={name} onChange={(event) => setName(event.target.value)} required /></label><label htmlFor="provider-base-url">Base URL<input id="provider-base-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required /></label><label htmlFor="provider-generation-model">Generation model<input id="provider-generation-model" value={generationModel} onChange={(event) => setGenerationModel(event.target.value)} required /></label><label htmlFor="provider-embedding-model">Embedding model<input id="provider-embedding-model" value={embeddingModel} onChange={(event) => setEmbeddingModel(event.target.value)} /></label><label htmlFor="provider-api-key">API key <span className="field-note">optional for local providers</span><input id="provider-api-key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={kind === "ollama" || kind === "mlx" ? "Not required" : "Enter once; it is encrypted"} /></label><button type="submit" disabled={busy}>{busy ? "Saving…" : "Save & continue"}</button></form>{message ? <div className="status-card" role="status"><p>{message}</p></div> : null}{error ? <div className="status-card error-card" role="alert"><p>{error}</p></div> : null}</section></main>;
}
