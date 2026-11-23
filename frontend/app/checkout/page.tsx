"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { rs, uid } from "@/lib/format";
import type { Cart, Order } from "@/lib/types";
import RequireRole from "@/components/RequireRole";
import { Alert, Button, Card, Input, Loading } from "@/components/ui";

function CheckoutInner() {
  const { user, refreshCart, setUser } = useAuth();
  const router = useRouter();
  const [cart, setCart] = useState<Cart | null>(null);
  const [d, setD] = useState({ customer_name: user?.full_name || "", phone: user?.phone || "", address: user?.address || "",
    city: user?.city || "", postal_code: user?.postal_code || "" });
  const [step, setStep] = useState<"details" | "review">("details");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const key = useRef(uid()); // one idempotency key per checkout attempt → double clicks can't create duplicates

  useEffect(() => { api<Cart>("/api/cart").then(setCart).catch((e) => setErr(e.message)); }, []);

  async function place() {
    setBusy(true); setErr("");
    try {
      const res = await api<{ orders: Order[] }>("/api/checkout", { method: "POST", headers: { "Idempotency-Key": key.current },
        body: { delivery: d, confirm: true, save_details: true } });
      await refreshCart();
      if (user) setUser({ ...user, phone: d.phone, address: d.address, city: d.city, postal_code: d.postal_code });
      router.push(`/orders?placed=${res.orders.map((o) => o.id).join(",")}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Checkout failed");
      key.current = uid();
    } finally { setBusy(false); }
  }

  if (!cart) return err ? <Alert>{err}</Alert> : <Loading />;
  if (!cart.items.length) return <Alert tone="amber">Your cart is empty. <Link href="/" className="underline">Go shopping</Link></Alert>;
  const valid = d.customer_name.trim() && d.phone.trim().length >= 5 && d.address.trim().length >= 5 && d.city.trim().length >= 2;

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-semibold">Checkout</h1>
      <div className="mt-2 flex gap-2 text-sm text-slate-500"><span className={step === "details" ? "font-medium text-brand-700" : ""}>1. Delivery</span>›<span className={step === "review" ? "font-medium text-brand-700" : ""}>2. Review & confirm</span></div>
      {err && <div className="mt-4"><Alert>{err}</Alert></div>}
      {step === "details" ? (
        <Card className="mt-6 space-y-4 p-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Full name" value={d.customer_name} onChange={(e) => setD({ ...d, customer_name: e.target.value })} required />
            <Input label="Phone" value={d.phone} onChange={(e) => setD({ ...d, phone: e.target.value })} required />
          </div>
          <Input label="Address" value={d.address} onChange={(e) => setD({ ...d, address: e.target.value })} required />
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="City" value={d.city} onChange={(e) => setD({ ...d, city: e.target.value })} required />
            <Input label="Postal code (optional)" value={d.postal_code} onChange={(e) => setD({ ...d, postal_code: e.target.value })} />
          </div>
          <Button disabled={!valid} onClick={() => setStep("review")}>Continue to review</Button>
        </Card>
      ) : (
        <Card className="mt-6 space-y-4 p-6">
          <h2 className="font-semibold">Order summary</h2>
          <ul className="divide-y divide-slate-100 text-sm">
            {cart.items.map((i) => (
              <li key={i.item_id} className="flex justify-between py-2">
                <span>{i.quantity} × {i.name}{i.size ? ` (${i.size})` : ""} <span className="text-slate-400">· {i.store.name}</span></span>
                <span>{rs(i.subtotal)}</span>
              </li>))}
          </ul>
          <div className="flex justify-between text-lg font-semibold"><span>Total</span><span>{rs(cart.total)}</span></div>
          <div className="rounded-lg bg-slate-50 p-3 text-sm">
            <p className="font-medium">Deliver to</p>
            <p>{d.customer_name}, {d.phone}</p><p>{d.address}, {d.city} {d.postal_code}</p>
            <button onClick={() => setStep("details")} className="mt-1 text-brand-600 hover:underline">Edit</button>
          </div>
          <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-800">
            <strong>Mock payment:</strong> this is a demo checkout — no card is needed and no real money is charged.
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-0.5" />
            I confirm this order and delivery details are correct.
          </label>
          <Button onClick={place} loading={busy} disabled={!confirm} className="w-full">Place order · {rs(cart.total)}</Button>
        </Card>
      )}
    </div>
  );
}

export default function CheckoutPage() { return <RequireRole role="customer"><CheckoutInner /></RequireRole>; }
