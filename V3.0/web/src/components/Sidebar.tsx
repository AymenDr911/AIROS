"use client";
/* AIROS V3 - persistent sidebar navigation (user request).
   Lets users navigate between Dashboard and Profile (view/update) from any page. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { logout } from "@/lib/airos";

const NAV = [
  { href: "/app", label: "Dashboard", icon: "◫" },
  { href: "/profile", label: "My Profile", icon: "☐" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 shrink-0 border-r border-border bg-surface min-h-screen flex flex-col">
      <div className="px-4 py-4 border-b border-border flex items-center gap-2 font-bold">
        <span className="w-3 h-3 rounded-full bg-brand" aria-hidden="true" />
        AIROS <span className="text-muted font-normal text-sm">V3</span>
      </div>
      <nav className="flex-1 px-2 py-3 flex flex-col gap-1">
        {NAV.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={
                "flex items-center gap-2 px-3 py-2 rounded-lg text-sm " +
                (active
                  ? "bg-brand/10 text-brand font-semibold"
                  : "text-text hover:bg-bg")
              }
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="px-2 py-3 border-t border-border">
        <button
          type="button"
          onClick={() => logout()}
          className="w-full text-left px-3 py-2 rounded-lg text-sm text-muted hover:bg-bg"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}