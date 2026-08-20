import type { Metadata } from "next";
import "./globals.css";
import "katex/dist/katex.min.css";
import "@xyflow/react/dist/style.css";

export const metadata: Metadata = {
  title: "PaperLens",
  description: "Turn research papers into visual, verifiable explanations.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
