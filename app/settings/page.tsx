"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../auth-context";
import { fetchJson } from "../lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const { setUser, logout: clearAuth } = useAuth();
  const [profile, setProfile] = useState<{ email?: string; username?: string; bankroll?: number; subscription_tier?: string } | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      router.push("/login");
      return;
    }

    fetchJson<any>("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((payload) => {
        setProfile(payload);
        setUser(payload);
      })
      .catch(() => router.push("/login"));
  }, [router]);

  const logout = () => {
    clearAuth();
    router.push("/login");
  };

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
        <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-8 shadow-2xl shadow-black/25">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Account settings</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight">Your profile</h1>
            </div>
            <button onClick={logout} className="rounded-xl border border-white/10 px-4 py-2 text-sm text-zinc-300">Logout</button>
          </div>

          <div className="mt-8 grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-black/20 p-5">
              <p className="text-sm text-zinc-500">Email</p>
              <p className="mt-2 font-medium">{profile?.email ?? "—"}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/20 p-5">
              <p className="text-sm text-zinc-500">Username</p>
              <p className="mt-2 font-medium">{profile?.username ?? "—"}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/20 p-5">
              <p className="text-sm text-zinc-500">Subscription</p>
              <p className="mt-2 font-medium">{profile?.subscription_tier ?? "free"}</p>
            </div>
          </div>

          <div className="mt-8 rounded-2xl border border-white/10 bg-black/20 p-5">
            <p className="text-sm text-zinc-500">Bankroll</p>
            <p className="mt-2 text-3xl font-semibold">${profile?.bankroll?.toFixed(2) ?? "10,000.00"}</p>
          </div>
        </div>
      </div>
    </main>
  );
}
