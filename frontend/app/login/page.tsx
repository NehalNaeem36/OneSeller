"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Alert, Button, Card, Input, Loading } from "@/components/ui";

function Inner() {
  const { login } = useAuth();
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const u = await login(email, password);
      router.push(next && next.startsWith("/") ? next : u.role === "seller" ? "/seller" : "/");
    } catch (er) { setErr(er instanceof ApiError ? er.message : "Login failed"); } finally { setBusy(false); }
  }
  return (
    <Card className="mx-auto mt-8 max-w-md p-8">
      <h1 className="text-2xl font-semibold">Welcome back</h1>
      <form onSubmit={submit} className="mt-6 space-y-4">
        {err && <Alert>{err}</Alert>}
        <Input label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <Input label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <Button loading={busy} className="w-full">Log in</Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500">New here? <Link href="/register" className="text-brand-600 underline">Create an account</Link></p>
      <p className="mt-4 rounded-lg bg-slate-50 p-3 text-xs text-slate-500">Demo: customer@demo.oneseller.ai · seller urbanthreads@demo.oneseller.ai — password demo12345</p>
    </Card>
  );
}
export default function LoginPage() { return <Suspense fallback={<Loading />}><Inner /></Suspense>; }
