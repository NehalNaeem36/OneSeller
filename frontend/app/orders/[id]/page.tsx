"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Order } from "@/lib/types";
import RequireRole from "@/components/RequireRole";
import { Alert, Loading } from "@/components/ui";
import OrderDetail from "@/components/OrderDetail";

function Inner() {
  const { id } = useParams<{ id: string }>();
  const [o, setO] = useState<Order | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<Order>(`/api/orders/${id}`).then(setO).catch((e) => setErr(e.message)); }, [id]);
  if (err) return <Alert>{err}</Alert>;
  if (!o) return <Loading />;
  return <div className="mx-auto max-w-2xl space-y-4"><Link href="/orders" className="text-sm text-brand-600">← All orders</Link><OrderDetail o={o} /></div>;
}

export default function OrderPage() { return <RequireRole role="customer"><Inner /></RequireRole>; }
