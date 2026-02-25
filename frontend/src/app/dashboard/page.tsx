"use client";

import { useState, useEffect } from "react";
import { Plus, Trash2, ShieldAlert, Route } from "lucide-react";

type Subscription = {
    id: string;
    origin: string;
    destination: string;
    area: string;
    startTime: string;
    endTime: string;
};

export default function Dashboard() {
    const [subs, setSubs] = useState<Subscription[]>([]);
    const [loading, setLoading] = useState(true);
    const [phone, setPhone] = useState("");
    const [form, setForm] = useState({ origin: "", destination: "", area: "Los Angeles", startTime: "07:00", endTime: "09:00" });
    const [adding, setAdding] = useState(false);

    useEffect(() => {
        fetchSubs();
        fetchPhone();
    }, []);

    const fetchSubs = async () => {
        const res = await fetch("/api/subscriptions");
        setSubs(await res.json());
        setLoading(false);
    };

    const fetchPhone = async () => {
        const res = await fetch("/api/user");
        const data = await res.json();
        setPhone(data.phone || "");
    };

    const savePhone = async () => {
        await fetch("/api/user", { method: "POST", body: JSON.stringify({ phone }) });
        alert("Phone saved!");
    };

    const addRoute = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form.origin || !form.destination || !form.area) return;
        setAdding(true);
        try {
            const res = await fetch("/api/subscriptions", {
                method: "POST", body: JSON.stringify(form)
            });
            if (!res.ok) {
                const err = await res.json();
                alert(err.error || "Failed to add route.");
            } else {
                const newSub = await res.json();
                setSubs([...subs, newSub]);
                setForm({ ...form, origin: "", destination: "" }); // reset text fields
            }
        } catch (e) {
            alert("Error adding route.");
        } finally {
            setAdding(false);
        }
    };

    const deleteRoute = async (id: string) => {
        await fetch(`/api/subscriptions?id=${id}`, { method: "DELETE" });
        setSubs(subs.filter(s => s.id !== id));
    };

    return (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
            <h1 className="text-3xl font-extrabold tracking-tight mb-2">Monitored Routes</h1>
            <p className="text-slate-500 mb-8 max-w-2xl">
                Add the Point A and Point B of your commute. You'll only be alerted during the specified time windows.
            </p>

            {/* Phone number setup */}
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-8 flex flex-col md:flex-row md:items-end gap-4">
                <div className="flex-1">
                    <label className="block text-sm font-semibold text-slate-700 mb-1">Phone Number for Alerts</label>
                    <input
                        type="tel"
                        value={phone}
                        onChange={e => setPhone(e.target.value)}
                        placeholder="+1 234 567 8900"
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-emerald-500 outline-none transition-shadow"
                    />
                </div>
                <button onClick={savePhone} className="px-6 py-2 bg-slate-900 text-white font-medium rounded-lg hover:bg-slate-800 transition-colors">
                    Save Phone
                </button>
            </div>

            {/* Add new route */}
            <form onSubmit={addRoute} className="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-8 flex flex-col gap-4">
                <div className="flex flex-col lg:flex-row gap-4 items-end">
                    <div className="w-full lg:w-48">
                        <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Area</label>
                        <select value={form.area} onChange={e => setForm({ ...form, area: e.target.value })} className="w-full px-4 py-2.5 bg-white border border-slate-200 text-slate-800 rounded-xl focus:ring-2 focus:ring-emerald-500 outline-none font-medium appearance-none">
                            <option>Los Angeles</option>
                            <option>Orange County</option>
                            <option>San Diego</option>
                            <option>Bay Area</option>
                        </select>
                    </div>

                    <div className="flex-1 w-full">
                        <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Origin Address/Location</label>
                        <input required type="text" value={form.origin} onChange={e => setForm({ ...form, origin: e.target.value })} placeholder="e.g. 100 Main St, LA" className="w-full px-4 py-2.5 border border-slate-200 text-slate-900 placeholder:text-slate-400 rounded-xl focus:ring-2 focus:ring-emerald-500 outline-none font-medium" />
                    </div>

                    <div className="flex-1 w-full">
                        <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Destination</label>
                        <input required type="text" value={form.destination} onChange={e => setForm({ ...form, destination: e.target.value })} placeholder="e.g. LAX Airport" className="w-full px-4 py-2.5 border border-slate-200 text-slate-900 placeholder:text-slate-400 rounded-xl focus:ring-2 focus:ring-emerald-500 outline-none font-medium" />
                    </div>

                    <div className="w-full lg:w-auto lg:flex-1">
                        <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Times</label>
                        <div className="flex items-center gap-2">
                            <input required type="time" disabled={adding} value={form.startTime} onChange={e => setForm({ ...form, startTime: e.target.value })} className="w-full px-3 py-2.5 border border-slate-200 text-slate-800 rounded-xl focus:ring-2 focus:ring-emerald-500 outline-none text-sm font-medium" />
                            <span className="text-slate-400">-</span>
                            <input required type="time" disabled={adding} value={form.endTime} onChange={e => setForm({ ...form, endTime: e.target.value })} className="w-full px-3 py-2.5 border border-slate-200 text-slate-800 rounded-xl focus:ring-2 focus:ring-emerald-500 outline-none text-sm font-medium" />
                        </div>
                    </div>
                </div>

                <div className="flex justify-end mt-2 pt-2 border-t border-slate-100">
                    <button type="submit" disabled={adding} className="w-full lg:w-auto px-6 py-2.5 bg-emerald-500 text-white font-bold rounded-xl hover:bg-emerald-600 transition-colors flex items-center justify-center gap-2 disabled:opacity-50 tracking-wide text-sm">
                        {adding ? "Calculating Route..." : <><Plus className="w-4 h-4" /> Add Route</>}
                    </button>
                </div>
            </form>

            {/* Subscription List */}
            <h2 className="text-xl font-bold mb-4">Your Subscriptions</h2>
            {loading ? (
                <div className="h-32 flex items-center justify-center text-slate-400 animate-pulse">Loading...</div>
            ) : subs.length === 0 ? (
                <div className="bg-slate-100 rounded-2xl p-12 text-center text-slate-500 border border-slate-200 border-dashed">
                    <ShieldAlert className="w-12 h-12 text-slate-400 mx-auto mb-3" />
                    <p>You aren't monitoring any routes yet.</p>
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    {subs.map(sub => (
                        <div key={sub.id} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between group hover:border-emerald-200 transition-colors">
                            <div className="flex items-start gap-3">
                                <div className="p-2 bg-slate-100 rounded-lg mt-1">
                                    <Route className="w-5 h-5 text-slate-500" />
                                </div>
                                <div>
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="font-bold text-lg">{sub.origin}</span>
                                        <span className="text-slate-400">→</span>
                                        <span className="font-bold text-lg">{sub.destination}</span>
                                        <span className="text-xs px-2 py-1 bg-slate-100 rounded-md font-medium text-slate-600">{sub.area}</span>
                                    </div>
                                    <div className="text-sm text-slate-500 mt-1 font-medium bg-emerald-50 inline-block px-2 py-0.5 rounded text-emerald-700">
                                        Active between {sub.startTime} and {sub.endTime}
                                    </div>
                                </div>
                            </div>
                            <button
                                onClick={() => deleteRoute(sub.id)}
                                className="text-slate-400 hover:text-red-500 p-2 rounded-lg hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100"
                            >
                                <Trash2 className="w-5 h-5" />
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
