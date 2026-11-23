"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import RequireRole from "@/components/RequireRole";
import { cx } from "@/lib/format";

const NAV = [["/seller", "Dashboard"], ["/seller/products", "Products"], ["/seller/import", "Import"], ["/seller/orders", "Orders"],
  ["/seller/store", "Storefront"], ["/seller/billing", "Billing"]];

export default function SellerLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <RequireRole role="seller">
      <div className="mb-6 flex gap-1 overflow-x-auto rounded-xl border border-slate-200 bg-white p-1 text-sm">
        {NAV.map(([href, label]) => (
          <Link key={href} href={href} className={cx("whitespace-nowrap rounded-lg px-4 py-2", path === href ? "bg-brand-600 text-white" : "hover:bg-slate-100")}>{label}</Link>))}
      </div>
      {children}
    </RequireRole>
  );
}
