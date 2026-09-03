"use client";
/* AIROS V3 - landing (parity port of app/index.html). */
import { useState } from "react";
import Link from "next/link";
import { login, setLocale, getLocale } from "@/lib/airos";

export default function LandingPage() {
  const [err, setErr] = useState<string | null>(null);
  const [locale, setLocaleState] = useState<string>("en");

  async function go(mode?: "login" | "signup") {
    try {
      await login(mode);
    } catch (e) {
      setErr((e as Error)?.message || "Unexpected error");
    }
  }

  function pickLocale(loc: string) {
    try {
      setLocale(loc);
      setLocaleState(loc);
    } catch (e) {
      setErr((e as Error)?.message || "Unexpected error");
    }
  }

  return (
    <section className="text-center py-10">
      <h1 className="text-4xl font-bold m-1">Welcome to AIROS V3</h1>
      <p className="text-muted max-w-xl mx-auto mt-3 mb-6">
        Your career companion. Sign in with Auth0 to sync your account and enter the app.
      </p>
      <div className="flex flex-wrap justify-center gap-4 text-sm text-muted mb-6">
        <span>1. Sign in</span>
        <span>2. Verify your email (optional, recommended)</span>
        <span>3. Build your profile</span>
      </div>
      <div className="flex flex-col items-center gap-3">
        <button type="button" onClick={() => go()} className="btn-primary">
          Continue with Auth0
        </button>
        <button type="button" onClick={() => go("signup")} className="btn-secondary">
          Create an account
        </button>
      </div>
      <div className="flex justify-center gap-2 my-5">
        {["en", "fr"].map((loc) => (
          <button
            key={loc}
            type="button"
            data-locale={loc}
            onClick={() => pickLocale(loc)}
            className={
              "btn-secondary min-w-12 " + (getLocale() === loc || locale === loc ? "!border-brand !text-brand" : "")
            }
          >
            {loc.toUpperCase()}
          </button>
        ))}
      </div>
      <p className="text-sm text-muted">Language affects the Auth0 login prompts (ui_locales).</p>
      <p className="text-sm text-muted mt-1">
        Already signed in?{" "}
        <Link href="/app" className="text-brand underline underline-offset-2">
          Open the app
        </Link>
      </p>
      {err != null && (
        <p role="alert" className="text-danger text-sm mt-4">
          {err}
        </p>
      )}
    </section>
  );
}
