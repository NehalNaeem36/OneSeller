export const rs = (v: number) => `Rs. ${Math.round(v).toLocaleString("en-PK")}`;
export const date = (iso: string) =>
  new Date(iso).toLocaleDateString("en-PK", { day: "numeric", month: "short", year: "numeric" });
export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-PK", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export const uid = () =>
  (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36));
