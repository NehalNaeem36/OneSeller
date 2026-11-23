"use client";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { cx, date, rs } from "@/lib/format";
import type { Subscription } from "@/lib/types";
import SubscriptionBanner from "@/components/SubscriptionBanner";
import { Alert, Button, Card, Loading, Modal } from "@/components/ui";

type Billing = Subscription & { payments: { reference: string; plan: string; amount: number; created_at: string }[] };

export default function BillingPage() {
  const [b, setB] = useState<Billing | null>(null);
  const [payFor, setPayFor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const load = useCallback(() => api<Billing>("/api/seller/billing").then(setB).catch((e) => setMsg({ tone: "red", text: e.message })), []);
  useEffect(() => { load(); }, [load]);
  if (!b) return msg ? <Alert>{msg.text}</Alert> : <Loading />;

  async function pay() {
    setBusy(true);
    try {
      const r = await api<{ payment_reference: string; action: string }>("/api/seller/billing/pay", { method: "POST", body: { plan: payFor } });
      setMsg({ tone: "green", text: `Mock payment ${r.payment_reference} succeeded — plan ${r.action}.` }); setPayFor(null); load();
    } catch (e) { setMsg({ tone: "red", text: e instanceof ApiError ? e.message : "Payment failed" }); } finally { setBusy(false); }
  }
  async function expire() {
    if (!confirm("Simulate expiry? Your products will be hidden until you renew.")) return;
    await api("/api/seller/billing/simulate-expiry", { method: "POST" }); load();
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Billing & subscription</h1>
      <SubscriptionBanner s={b} />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="grid gap-4 md:grid-cols-3">
        {Object.entries(b.plans).map(([key, p]) => {
          const current = b.plan === key;
          return (
            <Card key={key} className={cx("flex flex-col p-5", current && "ring-2 ring-brand-500")}>
              <p className="font-semibold">{p.name} {current && <span className="text-xs text-brand-600">(current)</span>}</p>
              <p className="mt-1 text-2xl font-bold">{p.price ? rs(p.price) : "Free"}<span className="text-sm font-normal text-slate-500">{p.price ? " / month" : " · 1 month"}</span></p>
              <ul className="mt-3 flex-1 space-y-1 text-sm text-slate-600">{p.features.map((f) => <li key={f}>✓ {f}</li>)}</ul>
              {key !== "trial" && <Button className="mt-4" variant={current ? "secondary" : "primary"} onClick={() => setPayFor(key)}>
                {current && b.status === "active" ? "Renew (+1 month)" : current ? "Reactivate" : "Upgrade"}</Button>}
            </Card>);
        })}
      </div>
      <Card className="p-5">
        <h2 className="mb-3 font-semibold">Payment history (mock)</h2>
        {b.payments.length === 0 ? <p className="text-sm text-slate-500">No payments yet.</p> : (
          <ul className="divide-y divide-slate-100 text-sm">{b.payments.map((p) => (
            <li key={p.reference} className="flex justify-between py-2"><span>{date(p.created_at)} · {p.plan} · <code className="text-xs">{p.reference}</code></span><span>{rs(p.amount)}</span></li>))}</ul>)}
      </Card>
      {b.simulation_enabled && <button onClick={expire} className="text-xs text-slate-400 underline">Demo: simulate subscription expiry</button>}
      <Modal open={!!payFor} onClose={() => setPayFor(null)} title="Mock payment">
        {payFor && <div className="space-y-4 text-sm">
          <p>Pay <strong>{rs(b.plans[payFor].price)}</strong> for one month of <strong>{b.plans[payFor].name}</strong>.</p>
          <Alert tone="blue">This is a simulated payment for the MVP. No card is needed and no real money is charged.</Alert>
          <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setPayFor(null)}>Cancel</Button><Button loading={busy} onClick={pay}>Pay (mock)</Button></div>
        </div>}
      </Modal>
    </div>
  );
}
