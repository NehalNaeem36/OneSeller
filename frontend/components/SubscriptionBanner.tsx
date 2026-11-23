import Link from "next/link";
import type { Subscription } from "@/lib/types";
import { date } from "@/lib/format";

export default function SubscriptionBanner({ s }: { s: Subscription }) {
  if (s.status === "expired") return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <strong>Your {s.is_trial ? "free trial" : "subscription"} has expired.</strong> Your products are hidden from the marketplace and new
      orders are paused. <Link href="/seller/billing" className="font-medium underline">Renew now</Link>
    </div>);
  return (
    <div className="rounded-xl border border-brand-100 bg-brand-50 p-4 text-sm text-brand-900">
      <strong>{s.plan_name}</strong> · active until {date(s.period_end)} ({s.days_remaining} days left) · {s.orders_used}/{s.order_limit} orders this period.
      {s.is_trial && <> <Link href="/seller/billing" className="font-medium underline">Upgrade</Link></>}
    </div>);
}
