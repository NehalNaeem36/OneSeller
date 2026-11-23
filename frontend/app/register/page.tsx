"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx } from "@/lib/format";
import { Alert, Button, Card, Input, Loading } from "@/components/ui";

function Inner() {
  const { register } = useAuth();
  const router = useRouter();
  const [role, setRole] = useState<"customer" | "seller">(useSearchParams().get("role") === "seller" ? "seller" : "customer");
  const [f, setF] = useState({ full_name: "", email: "", password: "", store_name: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const u = await register({ ...f, role, store_name: role === "seller" ? f.store_name : undefined });
      router.push(u.role === "seller" ? "/seller?welcome=1" : "/");
    } catch (er) { setErr(er instanceof ApiError ? er.message : "Registration failed"); } finally { setBusy(false); }
  }
  return (
    <Card className="mx-auto mt-8 max-w-md p-8">
      <h1 className="text-2xl font-semibold">Create your account</h1>
      <div className="mt-5 grid grid-cols-2 gap-2 rounded-lg bg-slate-100 p-1 text-sm">
        {(["customer", "seller"] as const).map((r) => (
          <button key={r} type="button" onClick={() => setRole(r)}
            className={cx("rounded-md py-2 font-medium", role === r ? "bg-white shadow-sm" : "text-slate-500")}>
            {r === "customer" ? "I want to shop" : "I want to sell"}
          </button>))}
      </div>
      {role === "seller" && <p className="mt-3 text-sm text-slate-600">Get your own storefront and AI sales agent. <strong>1-month free trial</strong>, no card needed.</p>}
      <form onSubmit={submit} className="mt-5 space-y-4">
        {err && <Alert>{err}</Alert>}
        <Input label="Full name" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required />
        {role === "seller" && <Input label="Store name" value={f.store_name} onChange={(e) => setF({ ...f, store_name: e.target.value })} required />}
        <Input label="Email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required />
        <Input label="Password (min 8 characters)" type="password" minLength={8} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />
        <Button loading={busy} className="w-full">{role === "seller" ? "Create store & start trial" : "Create account"}</Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500">Already have an account? <Link href="/login" className="text-brand-600 underline">Log in</Link></p>
    </Card>
  );
}
export default function RegisterPage() { return <Suspense fallback={<Loading />}><Inner /></Suspense>; }
