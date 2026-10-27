"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, MapPin, MessageSquareText, Pause, Play, ShieldAlert, X } from "lucide-react";

type AlertMessage = {
    id: string;
    subscriptionId: string;
    routeLabel: string;
    incidentNumber: string;
    kind: "NEW" | "UPDATE" | "RESOLVED" | "STALE" | "ACTIVE";
    matchMethod: "spatial" | "text" | null;
    distanceMiles: number | null;
    location: string | null;
    message: string;
    delivery: "twilio" | "mock" | "none";
    createdAt: string;
};

// Every alert about one incident on one route, newest first. A route only sees
// a handful of incidents inside the 48h log window, so the page lists these
// rather than individual messages; the messages live in the detail dialog.
type IncidentEvent = {
    key: string;
    routeLabel: string;
    incidentNumber: string;
    location: string | null;
    messages: AlertMessage[];
    latest: AlertMessage;
    status: IncidentStatus;
};

// Where an incident stands, from the last thing the worker logged about it.
// Stale means its route left the time window while it was open: it isn't being
// checked, so it is neither known to be active nor known to have cleared.
type IncidentStatus = "active" | "resolved" | "stale";

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
    STALE: "bg-slate-200 text-slate-700",
    ACTIVE: "bg-amber-100 text-amber-800",
};

const STATUS_PILLS: Record<IncidentStatus, { label: string; pill: string; dot: string }> = {
    active: { label: "Active", pill: "bg-amber-100 text-amber-800", dot: "bg-amber-500" },
    resolved: { label: "Resolved", pill: "bg-emerald-100 text-emerald-800", dot: "bg-emerald-500" },
    stale: { label: "Stale", pill: "bg-slate-200 text-slate-700", dot: "bg-slate-400" },
};

function statusOf(m: AlertMessage): IncidentStatus {
    if (m.kind === "RESOLVED") return "resolved";
    if (m.kind === "STALE") return "stale";
    return "active";
}

function eventKey(m: AlertMessage) {
    return `${m.subscriptionId}_${m.incidentNumber}`;
}

function formatRoute(label: string) {
    return label.replace("->", " → ");
}

function formatTime(iso: string) {
    const d = new Date(iso);
    const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    if (d.toDateString() === new Date().toDateString()) return time;
    return `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

// RESOLVED and STALE entries carry no match info, so describe the most recent alert that does.
function matchLabel(messages: AlertMessage[]) {
    const m = messages.find(x => x.matchMethod);
    if (m?.matchMethod === "spatial") {
        return m.distanceMiles != null ? `Within ${m.distanceMiles.toFixed(1)} mi of route` : "Near route";
    }
    if (m?.matchMethod === "text") return "Location text match";
    return null;
}

function groupEvents(messages: AlertMessage[]): IncidentEvent[] {
    const byKey = new Map<string, AlertMessage[]>();
    // messages is newest-first, and each group keeps that order.
    for (const m of messages) {
        const group = byKey.get(eventKey(m));
        if (group) group.push(m);
        else byKey.set(eventKey(m), [m]);
    }
    return [...byKey.entries()]
        .map(([key, msgs]) => {
            const latest = msgs[0];
            return {
                key,
                routeLabel: latest.routeLabel,
                incidentNumber: latest.incidentNumber,
                location: msgs.find(m => m.location)?.location ?? null,
                messages: msgs,
                latest,
                status: statusOf(latest),
            };
        })
        .sort((a, b) => b.latest.createdAt.localeCompare(a.latest.createdAt));
}

function StatusPill({ status }: { status: IncidentStatus }) {
    const { label, pill, dot } = STATUS_PILLS[status];
    return (
        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold ${pill}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${dot}`} /> {label}
        </span>
    );
}

function EventDialog({ event, onClose }: { event: IncidentEvent | null; onClose: () => void }) {
    const ref = useRef<HTMLDialogElement>(null);
    const list = useRef<HTMLOListElement>(null);

    useEffect(() => {
        const dialog = ref.current;
        if (!dialog) return;
        if (event && !dialog.open) {
            dialog.showModal();
            // A modal dialog doesn't stop the page behind it scrolling on touch devices.
            document.documentElement.style.overflow = "hidden";
        } else if (!event && dialog.open) {
            dialog.close();
        }
    }, [event]);

    // Newest is first, so a newly arrived message lands at the top; keep the list there.
    const count = event?.messages.length ?? 0;
    useEffect(() => {
        if (count) list.current?.scrollTo({ top: 0 });
    }, [count]);

    const match = event ? matchLabel(event.messages) : null;

    return (
        <dialog
            ref={ref}
            aria-labelledby="event-dialog-title"
            onClose={() => {
                document.documentElement.style.overflow = "";
                onClose();
            }}
            // Clicks on the backdrop land on the <dialog> itself; clicks inside land on its content.
            onClick={e => { if (e.target === ref.current) ref.current?.close(); }}
            className="p-0 bg-transparent max-w-none max-h-none w-full m-0 mt-auto sm:m-auto sm:max-w-lg backdrop:bg-slate-900/50 backdrop:backdrop-blur-sm"
        >
            {event && (
                <div className="flex flex-col max-h-[90dvh] sm:max-h-[80dvh] overflow-hidden bg-white rounded-t-2xl sm:rounded-2xl shadow-xl">
                    <div className="px-5 pt-3 pb-4 border-b border-slate-200">
                        {/* Spans the whole header so it centres on the sheet, not on the text column. */}
                        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-slate-200 sm:hidden" />
                        <div className="flex items-start gap-3">
                            <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2 mb-2">
                                    <StatusPill status={event.status} />
                                    <span className="text-xs text-slate-400">#{event.incidentNumber}</span>
                                </div>
                                <h2 id="event-dialog-title" className="text-lg font-bold text-slate-900 leading-snug">
                                    {event.location ?? `Incident #${event.incidentNumber}`}
                                </h2>
                                <p className="text-sm text-slate-500 mt-1">
                                    {formatRoute(event.routeLabel)}
                                    {match && <> · {match}</>}
                                </p>
                            </div>
                            <button
                                onClick={() => ref.current?.close()}
                                aria-label="Close"
                                className="-mr-2 p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
                            >
                                <X className="w-5 h-5" />
                            </button>
                        </div>
                    </div>

                    <ol ref={list} className="flex-1 overflow-y-auto overscroll-contain px-5 py-4 space-y-4 bg-slate-50">
                        {event.messages.map(m => (
                            <li key={m.id}>
                                <div className="flex items-center gap-2 mb-1.5 text-xs">
                                    <span className={`px-1.5 py-0.5 rounded font-semibold ${KIND_STYLES[m.kind]}`}>{m.kind}</span>
                                    <span className="text-slate-500 tabular-nums" title={new Date(m.createdAt).toLocaleString()}>
                                        {formatTime(m.createdAt)}
                                    </span>
                                    <span className={`ml-auto px-1.5 py-0.5 rounded font-medium ${DELIVERY_BADGES[m.delivery].className}`}>
                                        {DELIVERY_BADGES[m.delivery].label}
                                    </span>
                                </div>
                                <p className="rounded-2xl rounded-tl-sm bg-white border border-slate-200 px-4 py-3 text-sm text-slate-800 whitespace-pre-line break-words shadow-sm">
                                    {m.message}
                                </p>
                            </li>
                        ))}
                    </ol>
                </div>
            )}
        </dialog>
    );
}

export default function LiveMessages() {
    const [messages, setMessages] = useState<AlertMessage[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [paused, setPaused] = useState(false);
    const [routeFilter, setRouteFilter] = useState("all");
    const [fresh, setFresh] = useState<Set<string>>(new Set());
    const [openKey, setOpenKey] = useState<string | null>(null);
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
                const keys = added.map(eventKey);
                setFresh(f => new Set([...f, ...keys]));
                setTimeout(() => setFresh(f => {
                    const next = new Set(f);
                    keys.forEach(k => next.delete(k));
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

    const events = useMemo(() => groupEvents(messages), [messages]);
    const routes = useMemo(() => [...new Set(events.map(e => e.routeLabel))].sort(), [events]);
    const visible = routeFilter === "all" ? events : events.filter(e => e.routeLabel === routeFilter);
    const openEvent = events.find(e => e.key === openKey) ?? null;
    const anyMock = messages.some(m => m.delivery === "mock");
    const anyLogOnly = messages.some(m => m.delivery === "none");

    return (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-8">
                <div>
                    <h1 className="text-3xl font-extrabold tracking-tight mb-2">Live Messages</h1>
                    <p className="text-slate-500 max-w-2xl">
                        Incidents the worker picked up on your routes. Tap one to see every alert sent about it.
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
                        className="min-w-0 px-3 py-1.5 bg-white border border-slate-200 text-slate-800 rounded-lg text-sm font-medium focus:ring-2 focus:ring-emerald-500 outline-none"
                    >
                        <option value="all">All routes</option>
                        {routes.map(r => <option key={r} value={r}>{formatRoute(r)}</option>)}
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
                <ul className="space-y-3">
                    {visible.map(e => (
                        <li key={e.key}>
                            <button
                                onClick={() => setOpenKey(e.key)}
                                className={`group w-full text-left rounded-2xl border shadow-sm p-4 sm:p-5 flex items-center gap-3 transition-colors duration-1000 hover:border-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${fresh.has(e.key) ? "bg-emerald-50 border-emerald-200" : "bg-white border-slate-200"} ${e.status === "active" ? "" : "opacity-75"}`}
                            >
                                <div className="min-w-0 flex-1">
                                    <div className="flex items-center gap-2 mb-2 text-xs">
                                        <StatusPill status={e.status} />
                                        <span className="ml-auto text-slate-400 tabular-nums" title={new Date(e.latest.createdAt).toLocaleString()}>
                                            {formatTime(e.latest.createdAt)}
                                        </span>
                                    </div>
                                    <p className="flex items-start gap-1.5 font-semibold text-slate-900 leading-snug">
                                        <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                                        <span className="min-w-0 break-words">{e.location ?? `Incident #${e.incidentNumber}`}</span>
                                    </p>
                                    <p className="mt-1.5 text-sm text-slate-600 line-clamp-2 break-words">{e.latest.message}</p>
                                    <p className="mt-2 text-xs text-slate-400">
                                        <span className="font-medium text-slate-500">{formatRoute(e.routeLabel)}</span>
                                        {" · "}{e.messages.length} {e.messages.length === 1 ? "alert" : "alerts"}
                                        {matchLabel(e.messages) && <> · {matchLabel(e.messages)}</>}
                                    </p>
                                </div>
                                <ChevronRight className="h-5 w-5 shrink-0 text-slate-300 group-hover:text-slate-500 transition-colors" />
                            </button>
                        </li>
                    ))}
                </ul>
            )}

            <EventDialog event={openEvent} onClose={() => setOpenKey(null)} />
        </div>
    );
}
