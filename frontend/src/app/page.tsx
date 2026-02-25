import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { redirect } from "next/navigation";
import Link from "next/link";
import { LogIn, ArrowRight } from "lucide-react";

export default async function Home() {
  const session = await getServerSession(authOptions);

  if (session) {
    redirect("/dashboard");
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24 bg-gradient-to-b from-slate-900 to-slate-800 text-white">
      <div className="z-10 max-w-5xl w-full items-center justify-between font-mono text-sm flex flex-col gap-6 text-center">
        <h1 className="text-6xl font-extrabold tracking-tight">
          CHP Commute Alerts
        </h1>
        <p className="text-xl text-slate-300 max-w-2xl">
          Get real-time text message alerts when accidents or delays happen on your exact route, only during the times you care about.
        </p>

        <div className="mt-8 flex gap-4">
          <Link
            href="/api/auth/signin"
            className="group rounded-full border border-transparent px-8 py-3 transition-all bg-emerald-500 hover:bg-emerald-400 text-lg font-semibold flex items-center gap-2"
          >
            Get Started <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </Link>
          <Link
            href="/api/auth/signin"
            className="rounded-full border border-slate-600 px-8 py-3 hover:bg-slate-700 transition-colors text-lg font-semibold flex items-center gap-2"
          >
            <LogIn className="w-5 h-5" /> Sign In
          </Link>
        </div>
      </div>
    </main>
  );
}
