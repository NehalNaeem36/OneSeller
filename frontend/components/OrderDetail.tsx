import { dateTime, rs } from "@/lib/format";
import type { Order } from "@/lib/types";
import { Badge, Card, statusTone } from "./ui";

export default function OrderDetail({ o }: { o: Order }) {
  return (
    <Card className="space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Order #{o.id}</h1>
          <p className="text-sm text-slate-500">{dateTime(o.created_at)} · {o.store?.name} · payment: {o.payment_status.replace("_", " ")}</p>
        </div>
        <Badge tone={statusTone(o.status)}>{o.status}</Badge>
      </div>
      <ul className="divide-y divide-slate-100 text-sm">
        {o.items.map((i, k) => (
          <li key={k} className="flex justify-between py-2">
            <span>{i.quantity} × {i.name}{i.color ? ` · ${i.color}` : ""}{i.size ? ` · ${i.size}` : ""} <span className="text-slate-400">@ {rs(i.unit_price)}</span></span>
            <span>{rs(i.subtotal)}</span>
          </li>))}
      </ul>
      <div className="flex justify-between text-lg font-semibold"><span>Total</span><span>{rs(o.total)}</span></div>
      <div className="rounded-lg bg-slate-50 p-3 text-sm">
        <p className="font-medium">Delivery</p>
        <p>{o.delivery.customer_name} · {o.delivery.phone}</p>
        <p>{o.delivery.address}, {o.delivery.city} {o.delivery.postal_code || ""}</p>
      </div>
    </Card>
  );
}
