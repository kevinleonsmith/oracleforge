import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OracleForge Terminal",
  description: "Autonomous AI prediction markets on Gnosis Chain.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <header className="nav">
          <div className="wrap nav-in">
            <div className="brand">◇ ORACLEFORGE</div>
            <a className="btn" style={{ marginLeft: "auto" }} href="#markets">Launch Terminal</a>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
