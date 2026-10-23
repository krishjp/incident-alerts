"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageSquareText, Pause, Play, ShieldAlert } from "lucide-react";

type AlertMessage = {
    id: string;
    subscriptionId: string;
    routeLabel: string;
    incidentNumber: string;
    kind: "NEW" | "UPDATE" | "RESOLVED";
    matchMethod: "spatial" | "text" | null;
    distanceMiles: number | null;
    location: string | null;
    message: string;
    delivery: "twilio" | "mock" | "none";
    createdAt: string;
};

// The worker runs about once a minute, so polling faster than this only adds load.
const POLL_INTERVAL_MS = 5000;
const MAX_ROWS = 200;
const HIGHLIGHT_MS = 4000;

const DELIVERY_BADGES: Record<AlertMessage["delivery"], { label: string; className: string }> = {
    twilio: { label: "SMS", className: "bg-emerald-100 text-emerald-800" },
    mock: { label: "Mock", className: "bg-slate-100 text-slate-600" },
    none: { label: "Log only", className: "bg-slate-100 text-slate-600" },
};

const KIND_STYLES: Record<AlertMessage["kind"], string> = {
    NEW: "bg-amber-100 text-amber-800",
    UPDATE: "bg-sky-100 text-sky-800",
    RESOLVED: "bg-emerald-100 text-emerald-800",
};

function matchLabel(m: AlertMessage) {
    if (m.matchMethod === "spatial") {
        return m.distanceMiles != null ? `Within ${m.distanceMiles.toFixed(1)} mi of route` : "Near route";
    }
    if (m.matchMethod === "text") return "Location text match";
    return "Dropped from feed / out of range";
}

export default function LiveMessages() {
    const [messages, setMessages] = useState<AlertMessage[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [paused, setPaused] = useState(false);
    const [routeFilter, setRouteFilter] = useState("all");
    const [fresh, setFresh] = useState<Set<string>>(new Set());
    const newest = useRef<string | null>(null);
    const seen = useRef<Set<string>>(new Set());

    const poll = useCallback(async () => {
        try {
            const query = newest.current ? `?since=${encodeURIComponent(newest.current)}` : "";
            const res = await fetch(`/api/messages${query}`, { cache: "no-store" });
            if (!res.ok) throw new Error();
            const incoming: AlertMessage[] = await res.json();
            setError(null);
            if (incoming.length === 0) return;

            const isFirstLoad = newest.current === null;
            newest.current = incoming[0].createdAt;
            // The inclusive ?since bound re-sends the newest row(s) every poll.
            const added = incoming.filter(m => !seen.current.has(m.id));
            if (added.length === 0) return;
            added.forEach(m => seen.current.add(m.id));
            setMessages(prev => [...added, ...prev].slice(0, MAX_ROWS));

            if (!isFirstLoad) {
                const ids = added.map(m => m.id);
                setFresh(f => new Set([...f, ...ids]));
                setTimeout(() => setFresh(f => {
                    const next = new Set(f);
                    ids.forEach(id => next.delete(id));
                    return next;
                }), HIGHLIGHT_MS);
            }
        } catch {
            setError("Could not load messages. Retrying…");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (paused) return;
        poll();
        const timer = setInterval(poll, POLL_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [paused, poll]);

    const routes = useMemo(() => [...new Set(messages.map(m => m.routeLabel))].sort(), [messages]);
    const visible = routeFilter === "all" ? messages : messages.filter(m => m.routeLabel === routeFilter);
    const anyMock = messages.some(m => m.delivery === "mock");
    const anyLogOnly = messages.some(m => m.delivery === "none");

    return (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-8">
                <div>
                    <h1 className="text-3xl font-extrabold tracking-tight mb-2">Live Messages</h1>
                    <p className="text-slate-500 max-w-2xl">
                        Every alert the worker queues for you, as it happens, labeled by the route that picked it up.
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <span className="flex items-center gap-2 text-sm font-medium text-slate-600">
                        <span className={`h-2.5 w-2.5 rounded-full ${paused ? "bg-slate-400" : "bg-emerald-500 animate-pulse"}`} />
                        {paused ? "Paused" : "Live"}
                    </span>
                    <button
                        onClick={() => setPaused(p => !p)}
                        className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800 transition-colors flex items-center gap-2"
                    >
                        {paused ? <><Play className="w-4 h-4" /> Resume</> : <><Pause className="w-4 h-4" /> Pause</>}
                    </button>
                </div>
            </div>

            {anyMock && (
                <div role="status" className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                    Twilio isn&apos;t configured, so messages marked <span className="font-semibold">Mock</span> were
                    logged here instead of sent as SMS.
                </div>
            )}
            {anyLogOnly && (
                <div role="status" className="mb-6 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                    Messages marked <span className="font-semibold">Log only</span> weren&apos;t texted because no phone
                    number was saved. Add one on My Routes to get them by SMS.
                </div>
            )}
            {error && (
                <div role="alert" className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{error}</span>
                </div>
            )}

            {routes.length > 1 && (
                <div className="mb-4 flex items-center gap-2">
                    <label htmlFor="route-filter" className="text-xs font-bold text-slate-500 uppercase tracking-wider">Route</label>
                    <select
                        id="route-filter"
                        value={routeFilter}
                        onChange={e => setRouteFilter(e.target.value)}
                        className="px-3 py-1.5 bg-white border border-slate-200 text-slate-800 rounded-lg text-sm font-medium focus:ring-2 focus:ring-emerald-500 outline-none"
                    >
                        <option value="all">All routes</option>
                        {routes.map(r => <option key={r} value={r}>{r.replace("->", " → ")}</option>)}
                    </select>
                </div>
            )}

            {loading ? (
                <div className="h-32 flex items-center justify-center text-slate-400 animate-pulse">Loading...</div>
            ) : visible.length === 0 ? (
                <div className="bg-slate-100 rounded-2xl p-12 text-center text-slate-500 border border-slate-200 border-dashed">
                    <MessageSquareText className="w-12 h-12 text-slate-400 mx-auto mb-3" />
                    <p>No messages yet.</p>
                    <p className="text-sm mt-1">
                        Alerts appear here when an incident is found on an active route during its time window.
                    </p>
                </div>
            ) : (
                <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-slate-200 text-left text-xs font-bold text-slate-500 uppercase tracking-wider">
                                <th className="px-4 py-3 whitespace-nowrap">Time</th>
                                <th className="px-4 py-3">Route</th>
                                <th className="px-4 py-3">Type</th>
                                <th className="px-4 py-3">Detected by</th>
                                <th className="px-4 py-3 min-w-80">Message</th>
                                <th className="px-4 py-3">Delivery</th>
                            </tr>
                        </thead>
                        <tbody>
                            {visible.map(m => (
                                <tr
                                    key={m.id}
                                    className={`border-b border-slate-100 last:border-0 align-top transition-colors duration-1000 ${fresh.has(m.id) ? "bg-emerald-50" : ""}`}
                                >
                                    <td className="px-4 py-3 whitespace-nowrap text-slate-500 tabular-nums" title={new Date(m.createdAt).toLocaleString()}>
                                        {new Date(m.createdAt).toLocaleTimeString()}
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className="inline-block px-2 py-1 bg-slate-100 rounded-md font-medium text-slate-700 whitespace-nowrap">
                                            {m.routeLabel.replace("->", " → ")}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className={`inline-block px-2 py-0.5 rounded font-semibold text-xs ${KIND_STYLES[m.kind]}`}>
                                            {m.kind}
                                        </span>
                                        <div className="text-xs text-slate-400 mt-1 whitespace-nowrap">#{m.incidentNumber}</div>
                                    </td>
                                    <td className="px-4 py-3 text-slate-600">
                                        <div className="whitespace-nowrap">{matchLabel(m)}</div>
                                        {m.location && <div className="text-xs text-slate-400 mt-1">{m.location}</div>}
                                    </td>
                                    <td className="px-4 py-3 text-slate-800">{m.message}</td>
                                    <td className="px-4 py-3">
                                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${DELIVERY_BADGES[m.delivery].className}`}>
                                            {DELIVERY_BADGES[m.delivery].label}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}
