"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => { router.replace("/library"); }, [router]);
  return <main className="reader-loading"><div className="eyebrow">PAPERLENS</div><h1>Opening your library…</h1></main>;
}
