"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquareText, Route } from "lucide-react";

const LINKS = [
    { href: "/dashboard", label: "My Routes", icon: Route },
    { href: "/dashboard/messages", label: "Live Messages", icon: MessageSquareText },
];

// Client component only so the active link can follow the pathname; the
// dashboard layout itself stays a server component for the session check.
export default function DashboardNav() {
    const pathname = usePathname();
    return (
        <nav className="flex-1 flex flex-col gap-2">
            {LINKS.map(({ href, label, icon: Icon }) => {
                const active = pathname === href;
                return (
                    <Link
                        key={href}
                        href={href}
                        aria-current={active ? "page" : undefined}
                        className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-colors ${
                            active ? "bg-emerald-500/10 text-emerald-400 font-medium" : "hover:bg-slate-800 hover:text-white"
                        }`}
                    >
                        <Icon className="w-4 h-4" /> {label}
                    </Link>
                );
            })}
        </nav>
    );
}
