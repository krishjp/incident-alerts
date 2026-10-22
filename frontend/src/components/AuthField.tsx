"use client";

import { useId } from "react";

type Props = {
    label: string;
    type: string;
    value: string;
    onChange: (value: string) => void;
    onBlur?: () => void;
    /** Shown under the input (and marks it invalid) when set. */
    error?: string | null;
    hint?: string;
    placeholder?: string;
    autoComplete?: string;
};

/** Labelled auth-form input with inline validation feedback. */
export default function AuthField({
    label,
    type,
    value,
    onChange,
    onBlur,
    error,
    hint,
    placeholder,
    autoComplete,
}: Props) {
    const id = useId();
    const messageId = `${id}-message`;

    return (
        <div>
            <label htmlFor={id} className="block text-sm font-bold text-slate-700 mb-1">{label}</label>
            <div className="mt-1">
                <input
                    id={id}
                    type={type}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onBlur={onBlur}
                    placeholder={placeholder}
                    autoComplete={autoComplete}
                    aria-invalid={Boolean(error)}
                    aria-describedby={error || hint ? messageId : undefined}
                    className={`appearance-none block w-full px-4 py-3 border rounded-xl shadow-sm placeholder-slate-400 focus:outline-none focus:ring-2 sm:text-sm font-medium text-slate-900 ${error ? "border-red-400 focus:ring-red-400 focus:border-red-400" : "border-slate-300 focus:ring-emerald-500 focus:border-emerald-500"}`}
                />
            </div>
            {error ? (
                <p id={messageId} className="mt-1 text-xs font-semibold text-red-600">{error}</p>
            ) : hint ? (
                <p id={messageId} className="mt-1 text-xs text-slate-500">{hint}</p>
            ) : null}
        </div>
    );
}
