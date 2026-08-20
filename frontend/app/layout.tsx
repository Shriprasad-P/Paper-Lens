import type { Metadata } from "next";
import "./globals.css";

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
