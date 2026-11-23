import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import Navbar from "@/components/Navbar";
import ChatWidget from "@/components/ChatWidget";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "OneSeller AI — One Agent for every Seller",
  description: "A marketplace where every small seller gets an AI sales representative.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen font-sans antialiased">
        <AuthProvider>
          <Navbar />
          <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
          <footer className="mt-16 border-t border-slate-200 py-8 text-center text-xs text-slate-500">
            OneSeller AI · One Agent for every Seller · Mock payments only — no real money is charged.
          </footer>
          <ChatWidget />
        </AuthProvider>
      </body>
    </html>
  );
}
