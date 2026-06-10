import type { Metadata, Viewport } from "next";
import { DM_Sans, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { ClientShell } from "@/components/ui/ClientShell";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

/* Display face for marketing headlines only — the product UI stays DM Sans. */
const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  weight: ["500", "600", "700"],
});

export const viewport: Viewport = {
  themeColor: "#3b82f6",
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  userScalable: true,
};

export const metadata: Metadata = {
  metadataBase: new URL("https://checkmydata.ai"),
  title: {
    default: "CheckMyData.ai — Open-Source AI Database Agent",
    template: "%s | CheckMyData.ai",
  },
  description:
    "Open-source AI database agent. Ask in plain English and get correct SQL — it understands your schema and codebase. Works with PostgreSQL, MySQL, ClickHouse, and MongoDB.",
  manifest: "/manifest.json",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "16x16 32x32 48x48" },
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
  openGraph: {
    type: "website",
    siteName: "CheckMyData.ai",
    title: "CheckMyData.ai — Open-Source AI Database Agent",
    description:
      "Correct answers from your database in plain English — grounded in your schema and codebase. Open-source, privacy-first, self-hostable.",
    url: "https://checkmydata.ai",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "CheckMyData.ai — Open-source AI database agent",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "CheckMyData.ai — Open-Source AI Database Agent",
    description:
      "Correct answers from your database in plain English — grounded in your schema and codebase. Open-source, privacy-first, self-hostable.",
    images: ["/og-image.png"],
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "CheckMyData",
  },
  robots: {
    index: true,
    follow: true,
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${dmSans.variable} ${jetbrainsMono.variable} ${spaceGrotesk.variable} font-sans antialiased`}>
        <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-2 focus:left-2 focus:px-4 focus:py-2 focus:bg-accent focus:text-white focus:rounded-lg focus:text-sm">
          Skip to main content
        </a>
        <ClientShell>{children}</ClientShell>
      </body>
    </html>
  );
}
