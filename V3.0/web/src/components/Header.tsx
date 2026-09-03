"use client";
/* AIROS V3 - shared header: brand + theme toggle (theme works on every page,
   parity with the interim shell). */
import { toggleTheme } from "@/lib/airos";

export default function Header() {
  return (
    <header className="flex items-center justify-between gap-4 px-6 py-4 bg-surface border-b border-border">
      <div className="flex items-center gap-2.5 font-bold text-lg">
        <span className="w-3.5 h-3.5 rounded-full bg-brand" aria-hidden />
        AIROS <span className="text-muted font-normal">V3</span>
      </div>
      <nav className="flex items-center gap-2.5">
        <button type="button" onClick={toggleTheme} className="btn-secondary">
          Theme
        </button>
      </nav>
    </header>
  );
}
