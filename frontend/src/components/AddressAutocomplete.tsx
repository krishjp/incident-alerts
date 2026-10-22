"use client";

import { useEffect, useId, useRef, useState } from "react";
import { MapPin, Check } from "lucide-react";
import type { LatLon, Suggestion } from "@/lib/geo";

// Wait for a pause in typing before asking for suggestions; the upstream
// geocoder asks for fair use, and per-keystroke lookups are wasted anyway.
const DEBOUNCE_MS = 350;
const MIN_QUERY_LENGTH = 3;

type Props = {
    value: string;
    /** Coordinates of the picked suggestion, or null while the text is hand-typed. */
    place: LatLon | null;
    onChange: (value: string, place: LatLon | null) => void;
    placeholder?: string;
    disabled?: boolean;
    inputClassName?: string;
};

export default function AddressAutocomplete({
    value,
    place,
    onChange,
    placeholder,
    disabled,
    inputClassName,
}: Props) {
    const listId = useId();
    const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
    const [open, setOpen] = useState(false);
    const [highlight, setHighlight] = useState(-1);
    const [searching, setSearching] = useState(false);
    const wrapperRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        // A picked suggestion has nothing more to look up.
        if (place || value.trim().length < MIN_QUERY_LENGTH) {
            setSuggestions([]);
            return;
        }

        const controller = new AbortController();
        const timer = setTimeout(async () => {
            setSearching(true);
            try {
                const res = await fetch(`/api/geocode?q=${encodeURIComponent(value.trim())}`, {
                    signal: controller.signal,
                });
                const data = res.ok ? await res.json() : [];
                setSuggestions(Array.isArray(data) ? data : []);
                setHighlight(-1);
            } catch {
                // Aborted by a newer keystroke, or the lookup failed: the user can
                // still submit typed text, which the server geocodes itself.
            } finally {
                if (!controller.signal.aborted) setSearching(false);
            }
        }, DEBOUNCE_MS);

        return () => {
            clearTimeout(timer);
            controller.abort();
        };
    }, [value, place]);

    useEffect(() => {
        const close = (e: MouseEvent) => {
            if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
        };
        document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, []);

    const pick = (s: Suggestion) => {
        onChange(s.label, { lat: s.lat, lon: s.lon });
        setSuggestions([]);
        setOpen(false);
    };

    const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (!open || suggestions.length === 0) return;
        if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => (h + 1) % suggestions.length);
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => (h <= 0 ? suggestions.length - 1 : h - 1));
        } else if (e.key === "Enter" && highlight >= 0) {
            e.preventDefault(); // pick, don't submit the form
            pick(suggestions[highlight]);
        } else if (e.key === "Escape") {
            setOpen(false);
        }
    };

    const showList = open && suggestions.length > 0;

    return (
        <div ref={wrapperRef} className="relative">
            <input
                required
                type="text"
                role="combobox"
                aria-expanded={showList}
                aria-controls={listId}
                aria-autocomplete="list"
                autoComplete="off"
                disabled={disabled}
                value={value}
                placeholder={placeholder}
                onChange={(e) => {
                    // Any edit invalidates a previously picked place.
                    onChange(e.target.value, null);
                    setOpen(true);
                }}
                onFocus={() => setOpen(true)}
                onKeyDown={onKeyDown}
                className={`${inputClassName ?? ""} pr-9`}
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">
                {place ? (
                    <Check className="h-4 w-4 text-emerald-500" aria-label="Address confirmed" />
                ) : (
                    <MapPin className={`h-4 w-4 ${searching ? "animate-pulse text-emerald-400" : "text-slate-300"}`} />
                )}
            </span>
            {showList && (
                <ul
                    id={listId}
                    role="listbox"
                    className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg"
                >
                    {suggestions.map((s, i) => (
                        <li
                            key={`${s.label}-${i}`}
                            role="option"
                            aria-selected={i === highlight}
                            // mousedown, not click: fires before the input's blur.
                            onMouseDown={(e) => {
                                e.preventDefault();
                                pick(s);
                            }}
                            onMouseEnter={() => setHighlight(i)}
                            className={`flex cursor-pointer items-start gap-2 px-3 py-2 text-sm ${i === highlight ? "bg-emerald-50 text-emerald-900" : "text-slate-700"}`}
                        >
                            <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                            <span>{s.label}</span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
