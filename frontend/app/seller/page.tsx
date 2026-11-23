"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { dateTime, rs } from "@/lib/format";
import type { Order, Subscription } from "@/lib/types";
import SubscriptionBanner from "@/components/SubscriptionBanner";
import { Alert, Badge, Card, Empty, Loading, statusTone } from "@/components/ui";

interface Dash {
  store: { name: string; slug: string };
  kpis: { total_sales: number; total_orders: number; pending_orders: number; completed_orders: number; cancelled_orders: number;
    active_products: number; low_stock_products: number };
  low_stock: { id: number; name: string; stock: number }[]; recent_orders: Order[]; subscription: Subscription;
}

function Kpi({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return <Card className="p-4"><p className="text-xs uppercase tracking-wide text-slate-500">{label}</p><p className={`mt-1 text-2xl font-semibold ${tone || ""}`}>{value}</p></Card>;
}

export default function Dashboard() {
  const [d, setD] = useState<Dash | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<Dash>("/api/seller/dashboard").then(setD).catch((e) => setErr(e.message)); }, []);
  if (err) return <Alert>{err}</Alert>;
  if (!d) return <Loading />;
  const k = d.kpis;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-2xl font-semibold">{d.store.name}</h1>
          <Link href={`/store/${d.store.slug}`} className="text-sm text-brand-600 hover:underline">View storefront: /store/{d.store.slug} ↗</Link></div>
        <Link href="/seller/products?new=1" className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">+ Add product</Link>
      </div>
      <SubscriptionBanner s={d.subscription} />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Kpi label="Total sales" value={rs(k.total_sales)} />
        <Kpi label="Total orders" value={k.total_orders} />
        <Kpi label="Pending orders" value={k.pending_orders} tone={k.pending_orders ? "text-amber-600" : ""} />
        <Kpi label="Completed orders" value={k.completed_orders} tone="text-emerald-600" />
        <Kpi label="Active products" value={k.active_products} />
        <Kpi label="Low stock" value={k.low_stock_products} tone={k.low_stock_products ? "text-red-600" : ""} />
        <Kpi label="Cancelled" value={k.cancelled_orders} />
        <Kpi label={d.subscription.is_trial ? "Trial days left" : "Plan days left"} value={d.subscription.days_remaining} />
      </div>
      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <Card className="p-4">
          <div className="mb-3 flex justify-between"><h2 className="font-semibold">Recent orders</h2><Link href="/seller/orders" className="text-sm text-brand-600">All orders →</Link></div>
          {d.recent_orders.length === 0 ? <Empty title="No orders yet">Orders from the marketplace and the AI agent will appear here.</Empty> : (
            <ul className="divide-y divide-slate-100 text-sm">
              {d.recent_orders.map((o) => (
                <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>#{o.id} · {o.delivery.customer_name} · {o.items.map((i) => `${i.quantity}× ${i.name}`).join(", ")}</span>
                  <span className="flex items-center gap-2"><span className="text-xs text-slate-400">{dateTime(o.created_at)}</span>
                    <Badge tone={statusTone(o.status)}>{o.status}</Badge><strong>{rs(o.total)}</strong></span>
                </li>))}
            </ul>)}
        </Card>
        <Card className="p-4">
          <h2 className="mb-3 font-semibold">Low-stock products</h2>
          {d.low_stock.length === 0 ? <p className="text-sm text-slate-500">All stocked up 👍</p> : (
            <ul className="space-y-2 text-sm">
              {d.low_stock.map((p) => <li key={p.id} className="flex justify-between"><span className="truncate">{p.name}</span><Badge tone={p.stock ? "amber" : "red"}>{p.stock} left</Badge></li>)}
            </ul>)}
        </Card>
      </div>
    </div>
  );
}
