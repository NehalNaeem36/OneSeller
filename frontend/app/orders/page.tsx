"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { dateTime, rs } from "@/lib/format";
import type { Order } from "@/lib/types";
import RequireRole from "@/components/RequireRole";
import { Alert, Badge, Card, Empty, Loading, statusTone } from "@/components/ui";

function OrdersInner() {
  const placed = useSearchParams().get("placed");
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<Order[]>("/api/orders").then(setOrders).catch((e) => setErr(e.message)); }, []);
  if (err) return <Alert>{err}</Alert>;
  if (!orders) return <Loading />;
  return (
    <div>
      {placed && (
        <div className="mb-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-6 text-emerald-900">
          <p className="text-lg font-semibold">✅ Order confirmed!</p>
          <p className="text-sm">Order{placed.includes(",") ? "s" : ""} #{placed.split(",").join(", #")} placed. The seller has been notified.</p>
        </div>
      )}
      <h1 className="text-2xl font-semibold">My orders</h1>
      <div className="mt-6 space-y-3">
        {orders.length === 0 ? <Empty title="No orders yet"><Link href="/" className="text-brand-600 underline">Start shopping</Link></Empty> :
          orders.map((o) => (
            <Link key={o.id} href={`/orders/${o.id}`}>
              <Card className="flex flex-wrap items-center justify-between gap-3 p-4 transition hover:shadow-md">
                <div>
                  <p className="font-medium">Order #{o.id} · {o.store?.name}</p>
                  <p className="text-xs text-slate-500">{dateTime(o.created_at)} · {o.items.map((i) => `${i.quantity}× ${i.name}`).join(", ")}</p>
                </div>
                <div className="flex items-center gap-3">
                  {o.channel === "agent" && <Badge tone="brand">via AI</Badge>}
                  <Badge tone={statusTone(o.status)}>{o.status}</Badge>
                  <span className="font-semibold">{rs(o.total)}</span>
                </div>
              </Card>
            </Link>))}
      </div>
    </div>
  );
}

export default function OrdersPage() {
  return <RequireRole role="customer"><Suspense fallback={<Loading />}><OrdersInner /></Suspense></RequireRole>;
}
