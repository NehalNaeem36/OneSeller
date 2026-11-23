"use client";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import type { Order } from "@/lib/types";
import OrderDetail from "@/components/OrderDetail";
import { Alert, Badge, Button, Empty, Loading } from "@/components/ui";

const NEXT: Record<string, string[]> = { confirmed: ["processing", "shipped", "cancelled"], processing: ["shipped", "cancelled"],
  shipped: ["delivered"], delivered: [], cancelled: [] };
const FILTERS = ["", "confirmed", "processing", "shipped", "delivered", "cancelled"];

export default function SellerOrders() {
  const [status, setStatus] = useState("");
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const load = useCallback(() => api<Order[]>("/api/seller/orders", { query: { status } }).then(setOrders)
    .catch((e) => setMsg({ tone: "red", text: e.message })), [status]);
  useEffect(() => { load(); }, [load]);

  async function update(id: number, s: string) {
    if (s === "cancelled" && !confirm(`Cancel order #${id}? Stock will be returned.`)) return;
    try { await api(`/api/seller/orders/${id}`, { method: "PATCH", body: { status: s } }); setMsg({ tone: "green", text: `Order #${id} → ${s}` }); load(); }
    catch (e) { setMsg({ tone: "red", text: e instanceof ApiError ? e.message : "Update failed" }); }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Orders</h1>
      <div className="flex flex-wrap gap-1 text-sm">
        {FILTERS.map((f) => <button key={f} onClick={() => setStatus(f)}
          className={cx("rounded-full border px-3 py-1 capitalize", status === f ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white")}>{f || "all"}</button>)}
      </div>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {!orders ? <Loading /> : orders.length === 0 ? <Empty title="No orders" /> : orders.map((o) => (
        <div key={o.id} className="space-y-2">
          <OrderDetail o={o} />
          <div className="flex flex-wrap items-center gap-2 pl-1">
            {o.channel === "agent" && <Badge tone="brand">Placed via AI agent</Badge>}
            {NEXT[o.status].map((s) => <Button key={s} size="sm" variant={s === "cancelled" ? "danger" : "secondary"} onClick={() => update(o.id, s)}>Mark {s}</Button>)}
          </div>
        </div>))}
    </div>
  );
}
