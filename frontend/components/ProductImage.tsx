import { imageSrc } from "@/lib/api";
import { cx } from "@/lib/format";

const PALETTE = ["from-indigo-200 to-sky-100", "from-rose-200 to-amber-100", "from-emerald-200 to-teal-100",
  "from-violet-200 to-fuchsia-100", "from-amber-200 to-orange-100"];

export default function ProductImage({ url, name, className }: { url?: string | null; name: string; className?: string }) {
  const src = imageSrc(url);
  if (src) return <img src={src} alt={name} className={cx("object-cover", className)} />;
  const g = PALETTE[name.length % PALETTE.length];
  return (
    <div className={cx("flex items-center justify-center bg-gradient-to-br text-3xl font-semibold text-slate-600/70", g, className)}>
      {name.split(" ").slice(0, 2).map((w) => w[0]).join("").toUpperCase()}
    </div>
  );
}
