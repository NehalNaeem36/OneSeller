"use client";
import { useEffect } from "react";
import { cx } from "@/lib/format";

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; loading?: boolean;
};
export function Button({ variant = "primary", size = "md", loading, className, children, disabled, ...p }: BtnProps) {
  const v = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm",
    secondary: "bg-white text-slate-800 border border-slate-300 hover:bg-slate-50",
    ghost: "text-slate-600 hover:bg-slate-100",
    danger: "bg-red-600 text-white hover:bg-red-700",
  }[variant];
  return (
    <button {...p} disabled={disabled || loading}
      className={cx("inline-flex items-center justify-center gap-2 rounded-lg font-medium transition disabled:opacity-50 disabled:cursor-not-allowed",
        size === "sm" ? "px-3 py-1.5 text-sm" : "px-4 py-2.5 text-sm", v, className)}>
      {loading && <Spinner className="h-4 w-4" />}{children}
    </button>
  );
}

export function Input({ label, error, className, ...p }: React.InputHTMLAttributes<HTMLInputElement> & { label?: string; error?: string }) {
  return (
    <label className="block">
      {label && <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>}
      <input {...p} className={cx("w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100", className)} />
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  );
}

export function Textarea({ label, ...p }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string }) {
  return (
    <label className="block">
      {label && <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>}
      <textarea {...p} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100" />
    </label>
  );
}

export function Select({ label, children, className, ...p }: React.SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className="block">
      {label && <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>}
      <select {...p} className={cx("w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500", className)}>{children}</select>
    </label>
  );
}

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>{children}</div>;
}

export function Badge({ tone = "slate", children }: { tone?: "slate" | "green" | "amber" | "red" | "brand" | "blue"; children: React.ReactNode }) {
  const t = { slate: "bg-slate-100 text-slate-700", green: "bg-emerald-50 text-emerald-700", amber: "bg-amber-50 text-amber-700",
    red: "bg-red-50 text-red-700", brand: "bg-brand-50 text-brand-700", blue: "bg-sky-50 text-sky-700" }[tone];
  return <span className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", t)}>{children}</span>;
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cx("inline-block animate-spin rounded-full border-2 border-current border-t-transparent", className || "h-6 w-6 text-brand-600")} />;
}

export function Loading() {
  return <div className="flex justify-center py-16"><Spinner /></div>;
}

export function Alert({ tone = "red", children }: { tone?: "red" | "green" | "amber" | "blue"; children: React.ReactNode }) {
  const t = { red: "border-red-200 bg-red-50 text-red-800", green: "border-emerald-200 bg-emerald-50 text-emerald-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800", blue: "border-sky-200 bg-sky-50 text-sky-800" }[tone];
  return <div className={cx("rounded-lg border px-4 py-3 text-sm", t)}>{children}</div>;
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      <p className="font-medium text-slate-800">{title}</p>
      {children && <div className="mt-2 text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 p-4 sm:items-center" onClick={onClose}>
      <div className={cx("max-h-[90vh] w-full overflow-y-auto rounded-xl bg-white p-6 shadow-xl", wide ? "max-w-2xl" : "max-w-md")} onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function statusTone(s: string): "green" | "amber" | "red" | "blue" | "slate" {
  return ({ delivered: "green", confirmed: "blue", processing: "amber", shipped: "amber", cancelled: "red" } as const)[s as "delivered"] || "slate";
}
