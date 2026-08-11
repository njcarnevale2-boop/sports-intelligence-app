"use client";

import Link from "next/link";

export default function ForgotPasswordPage() {
  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-16 lg:flex-row lg:items-center lg:justify-between lg:px-10">
        <div className="max-w-xl">
          <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Password recovery</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">Reset your password</h1>
          <p className="mt-3 text-sm text-zinc-500">This flow is stubbed for the v1 launch, but the UI is ready for email-based recovery later.</p>
        </div>

        <div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#0B1119] p-7 shadow-2xl shadow-black/25">
          <label className="block text-sm text-zinc-400">Email</label>
          <input className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-3 text-sm text-white outline-none" type="email" placeholder="you@example.com" />
          <button className="mt-6 w-full rounded-xl bg-white px-4 py-3 font-medium text-black" type="button">Send reset link</button>
          <div className="mt-5 text-sm text-zinc-500"><Link href="/login" className="hover:text-white">Back to sign in</Link></div>
        </div>
      </div>
    </main>
  );
}
