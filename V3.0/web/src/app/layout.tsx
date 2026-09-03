import type { Metadata } from "next";
import Header from "@/components/Header";
import { themeBootstrapScript } from "@/lib/airos";
import "./globals.css";

export const metadata: Metadata = {
  title: "AIROS V3",
  description: "Your career companion. Auth0 + Supabase on the free plan.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} />
      </head>
      <body className="min-h-screen flex flex-col bg-bg text-text">
        <Header />
        <main className="flex-1 w-full max-w-3xl mx-auto px-4 py-6">{children}</main>
        <footer className="px-6 py-4 text-center text-xs text-muted border-t border-border">
          AIROS V3 - product UI (Slice 4a). Auth0 + Supabase. No Apple sign-in (DEC-015).
        </footer>
      </body>
    </html>
  );
}
