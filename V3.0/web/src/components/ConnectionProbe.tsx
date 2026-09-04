"use client";
/* AIROS V3 - small reachability probe for the Auth0 tenant (CHG-015).
   Shows a precise one-liner so network issues are diagnosable instead of a
   blind error. Safe to show on signed-out/error screens. */
import { useEffect, useState } from "react";
import { checkAuth0 } from "@/lib/airos";

export default function ConnectionProbe() {
  const [line, setLine] = useState("checking Auth0 connectivity...");
  useEffect(() => {
    let cancelled = false;
    checkAuth0().then((r) => {
      if (!cancelled) setLine(r.text);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return <p className="text-xs text-muted m-0">{line}</p>;
}