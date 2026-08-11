"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { fetchJson } from "../lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = await fetchJson<{ access_token: string; refresh_token: string }>(
        "/api/auth/register",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, username, password }),
        }
      );

      localStorage.setItem("access_token", payload.access_token);
      localStorage.setItem("refresh_token", payload.refresh_token);
      setMessage("Account created.");
      router.push("/settings");
    } catch {
      setMessage("Unable to create account.");
    }
  };

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-16 lg:flex-row lg:items-center lg:justify-between lg:px-10">
        <div className="max-w-xl">
          <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Join the platform</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">Create your account</h1>
          <p className="mt-3 text-sm text-zinc-500">Set your identity, bankroll preferences, and sportsbook defaults before you dive into the intelligence engine.</p>
        </div>

        <form onSubmit={submit} className="w-full max-w-md rounded-3xl border border-white/10 bg-[#0B1119] p-7 shadow-2xl shadow-black/25">
          <label className="block text-sm text-zinc-400">Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-3 text-sm text-white outline-none" type="email" required />

          <label className="mt-4 block text-sm text-zinc-400">Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-3 text-sm text-white outline-none" type="text" />

          <label className="mt-4 block text-sm text-zinc-400">Password</label>
          <input value={password} onChange={(e) => setPassword(e.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-3 text-sm text-white outline-none" type="password" required />

          <button className="mt-6 w-full rounded-xl bg-white px-4 py-3 font-medium text-black" type="submit">Create Account</button>
          {message ? <p className="mt-3 text-sm text-zinc-400">{message}</p> : null}
          <div className="mt-5 text-sm text-zinc-500"><Link href="/login" className="hover:text-white">Already have an account?</Link></div>
        </form>
      </div>
    </main>
  );
}
