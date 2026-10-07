import type { Metadata } from "next";
import { Geist_Mono, Manrope, Newsreader } from "next/font/google";
import Providers from "@/components/providers";
import "./globals.css";

const manrope = Manrope({ variable: "--font-manrope", subsets: ["latin"], display: "swap" });
const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], display: "swap" });
// Monospace appears only inside the API-call log.
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "Margin Mind",
  applicationName: "Margin Mind",
  openGraph: { siteName: "Margin Mind", title: "Margin Mind", description: "The decision engine behind your ad spend." },
  description: "The decision engine behind your ad spend.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-theme="dark" className={`dark ${manrope.variable} ${newsreader.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <body className="min-h-screen bg-ink font-sans text-bone antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
