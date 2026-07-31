import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { redirect } from "next/navigation";
import Link from "next/link";
import { BellRing, LogOut, Settings } from "lucide-react";

export default async function DashboardLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    const session = await getServerSession(authOptions);

    if (!session) {
        redirect("/api/auth/signin");
    }

    return (
        <div className="min-h-screen bg-slate-50 flex flex-col md:flex-row">
            {/* Sidebar */}
            <aside className="w-full md:w-64 bg-slate-900 text-slate-300 p-6 flex flex-col h-auto md:min-h-screen border-r border-slate-800">
                <div className="flex items-center gap-2 text-white mb-8">
                    <BellRing className="w-6 h-6 text-emerald-500" />
                    <span className="font-bold text-xl tracking-tight">Incident Alerts</span>
                </div>
                <nav className="flex-1 flex flex-col gap-2">
                    <Link href="/dashboard" className="px-4 py-2 rounded-lg bg-emerald-500/10 text-emerald-400 font-medium">
                        My Routes
                    </Link>
                    <Link href="/dashboard/settings" className="px-4 py-2 rounded-lg hover:bg-slate-800 hover:text-white transition-colors flex items-center gap-2">
                        <Settings className="w-4 h-4" /> Settings
                    </Link>
                </nav>
                <div className="mt-auto pt-8 border-t border-slate-800">
                    <div className="mb-4 text-sm font-medium">{session.user?.name || session.user?.email}</div>
                    <Link href="/api/auth/signout" className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors">
                        <LogOut className="w-4 h-4" /> Sign Out
                    </Link>
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 p-8 text-slate-900 max-w-5xl mx-auto w-full">
                {children}
            </main>
        </div>
    );
}
