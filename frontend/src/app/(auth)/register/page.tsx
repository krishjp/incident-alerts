"use client";

import { useState } from "react";
import Link from "next/link";
import { signIn } from "next-auth/react";
import { AlertCircle, Chrome } from "lucide-react";
import AuthField from "@/components/AuthField";
import {
    MIN_PASSWORD_LENGTH,
    validateIdentifier,
    validateName,
    validateNewPassword,
} from "@/lib/validation";

export default function Register() {
    const [name, setName] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    // Fields show their error once the user has left them (or tried to submit),
    // not while they are still typing.
    const [touched, setTouched] = useState({ name: false, email: false, password: false, confirm: false });
    const touch = (field: keyof typeof touched) => () => setTouched((t) => ({ ...t, [field]: true }));

    const errors = {
        name: validateName(name),
        email: validateIdentifier(email),
        password: validateNewPassword(password),
        confirm: confirmPassword !== password ? "Passwords don't match." : null,
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setTouched({ name: true, email: true, password: true, confirm: true });
        if (Object.values(errors).some(Boolean)) return;

        setLoading(true);
        setError("");

        try {
            const res = await fetch("/api/auth/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, email, password }),
            });

            if (res.ok) {
                // Automatically sign in the user
                await signIn("credentials", {
                    email,
                    password,
                    callbackUrl: "/dashboard",
                });
            } else {
                const data = await res.json();
                setError(data.error || "An error occurred");
                setLoading(false);
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : "Something went wrong.");
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-slate-50 flex flex-col justify-center py-12 px-6 lg:px-8">
            <div className="sm:mx-auto sm:w-full sm:max-w-md">
                <h2 className="mt-6 text-center text-4xl font-extrabold text-slate-900 tracking-tight">
                    Create a new account
                </h2>
                <p className="mt-2 text-center text-sm text-slate-600 font-medium">
                    Or{" "}
                    <Link href="/login" className="font-bold text-emerald-600 hover:text-emerald-500 transition-colors">
                        sign in to your existing account
                    </Link>
                </p>
            </div>

            <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
                <div className="bg-white py-8 px-4 shadow-sm sm:rounded-2xl sm:px-10 border border-slate-200">
                    <form className="space-y-6" onSubmit={handleSubmit} noValidate>
                        {error && (
                            <div className="flex items-center gap-2 p-3 text-red-700 bg-red-50 border border-red-200 rounded-lg text-sm font-bold">
                                <AlertCircle className="w-5 h-5 flex-shrink-0" />
                                {error}
                            </div>
                        )}

                        <AuthField
                            label="Full Name"
                            type="text"
                            autoComplete="name"
                            value={name}
                            onChange={setName}
                            onBlur={touch("name")}
                            error={touched.name ? errors.name : null}
                            placeholder="John Doe"
                        />

                        <AuthField
                            label="Email or username"
                            type="text"
                            autoComplete="username"
                            value={email}
                            onChange={setEmail}
                            onBlur={touch("email")}
                            error={touched.email ? errors.email : null}
                            placeholder="you@example.com or username"
                        />

                        <AuthField
                            label="Password"
                            type="password"
                            autoComplete="new-password"
                            value={password}
                            onChange={setPassword}
                            onBlur={touch("password")}
                            error={touched.password ? errors.password : null}
                            hint={`At least ${MIN_PASSWORD_LENGTH} characters, including a letter and a number.`}
                            placeholder="••••••••"
                        />

                        <AuthField
                            label="Confirm password"
                            type="password"
                            autoComplete="new-password"
                            value={confirmPassword}
                            onChange={setConfirmPassword}
                            onBlur={touch("confirm")}
                            error={touched.confirm ? errors.confirm : null}
                            placeholder="••••••••"
                        />

                        <div className="pt-2">
                            <button
                                type="submit"
                                disabled={loading}
                                className="w-full flex justify-center py-3 px-4 border border-transparent rounded-xl shadow-sm text-sm font-bold text-white bg-emerald-600 hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-emerald-500 transition-colors disabled:opacity-50"
                            >
                                {loading ? "Creating..." : "Create account"}
                            </button>
                        </div>
                    </form>

                    <div className="mt-8">
                        <div className="relative">
                            <div className="absolute inset-0 flex items-center">
                                <div className="w-full border-t border-slate-200" />
                            </div>
                            <div className="relative flex justify-center text-sm">
                                <span className="px-4 bg-white text-slate-500 font-medium tracking-wide">Or continue with</span>
                            </div>
                        </div>

                        <div className="mt-6">
                            <button
                                onClick={() => signIn('google', { callbackUrl: '/dashboard' })}
                                className="w-full inline-flex justify-center flex-row items-center gap-2 py-3 px-4 border border-slate-200 rounded-xl shadow-sm bg-white text-sm font-bold text-slate-600 hover:bg-slate-50 transition-colors transition-colors focus:ring-2 focus:ring-offset-2 focus:ring-slate-100"
                            >
                                <Chrome className="w-5 h-5 text-slate-500" />
                                <span>Google</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
