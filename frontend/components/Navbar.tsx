"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth";

export default function Navbar() {
  const { user, cartCount, logout, ready } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const seller = user?.role === "seller";

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
        <Link href={seller ? "/seller" : "/"} className="flex shrink-0 items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">1</span>
          <span className="hidden font-semibold sm:block">OneSeller <span className="text-brand-600">AI</span></span>
        </Link>
        {!seller && (
          <form className="flex-1" onSubmit={(e) => { e.preventDefault(); router.push(`/search?q=${encodeURIComponent(q)}`); }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search products, colors, stores…"
              className="w-full rounded-full border border-slate-300 bg-slate-50 px-4 py-2 text-sm outline-none focus:border-brand-500 focus:bg-white" />
          </form>
        )}
        {seller && <div className="flex-1" />}
        <nav className="hidden items-center gap-1 text-sm md:flex">
          {!seller && <Link className="rounded-lg px-3 py-2 hover:bg-slate-100" href="/stores">Stores</Link>}
          {seller && <>
            <Link className="rounded-lg px-3 py-2 hover:bg-slate-100" href="/seller">Dashboard</Link>
            <Link className="rounded-lg px-3 py-2 hover:bg-slate-100" href="/seller/products">Products</Link>
            <Link className="rounded-lg px-3 py-2 hover:bg-slate-100" href="/seller/orders">Orders</Link>
            <Link className="rounded-lg px-3 py-2 hover:bg-slate-100" href="/seller/store">Storefront</Link>
            <Link className="rounded-lg px-3 py-2 hover:bg-slate-100" href="/seller/billing">Billing</Link>
          </>}
          {user?.role === "customer" && <Link className="rounded-lg px-3 py-2 hover:bg-slate-100" href="/orders">Orders</Link>}
        </nav>
        {!seller && (
          <Link href="/cart" className="relative rounded-lg p-2 hover:bg-slate-100" aria-label="Cart">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 4h2l2.4 11.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.5L21 8H6" /><circle cx="10" cy="20" r="1.4" /><circle cx="17" cy="20" r="1.4" /></svg>
            {cartCount > 0 && <span className="absolute -right-0.5 -top-0.5 rounded-full bg-brand-600 px-1.5 text-[10px] font-semibold text-white">{cartCount}</span>}
          </Link>
        )}
        {ready && (user ? (
          <div className="relative">
            <button onClick={() => setOpen((o) => !o)} className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-800 text-sm font-medium text-white">
              {user.full_name[0]?.toUpperCase()}
            </button>
            {open && (
              <div className="absolute right-0 mt-2 w-52 rounded-xl border border-slate-200 bg-white p-1 text-sm shadow-lg" onMouseLeave={() => setOpen(false)}>
                <p className="truncate px-3 py-2 text-xs text-slate-500">{user.email}</p>
                {seller ? <>
                  {["/seller", "/seller/products", "/seller/orders", "/seller/store", "/seller/billing"].map((h) => (
                    <Link key={h} href={h} onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 capitalize hover:bg-slate-100 md:hidden">{h.split("/")[2] || "dashboard"}</Link>))}
                </> : <>
                  <Link href="/account" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 hover:bg-slate-100">Account & preferences</Link>
                  <Link href="/orders" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 hover:bg-slate-100">My orders</Link>
                  <Link href="/stores" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 hover:bg-slate-100 md:hidden">Stores</Link>
                </>}
                <button onClick={() => { logout(); setOpen(false); router.push("/"); }} className="block w-full rounded-lg px-3 py-2 text-left text-red-600 hover:bg-red-50">Log out</button>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-1 text-sm">
            <Link href="/login" className="rounded-lg px-3 py-2 hover:bg-slate-100">Log in</Link>
            <Link href="/register" className="hidden rounded-lg bg-brand-600 px-3 py-2 font-medium text-white hover:bg-brand-700 sm:block">Sign up</Link>
          </div>
        ))}
      </div>
    </header>
  );
}
