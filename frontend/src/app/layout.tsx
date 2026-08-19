import type { Metadata, Viewport } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { ClientShell } from "@/components/ui/ClientShell";
import { THEME_STORAGE_KEY } from "@/stores/theme-store";
import { ThemeWatcher } from "@/components/theme/ThemeWatcher";

/* The `ledger` pack's UI face. It fills `--font-ui-webfont`, which globals.css
   puts in front of the pack's own `--font-ui` stack — the pack keeps the
   fallback, the webfont is the preference. */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-ui-webfont",
  display: "swap",
});

/* Display face for marketing headlines only — the product UI never uses it.
   The pack's own display face is licensed and self-hosted by its reference,
   so per the pack this project points the product display at the UI face and
   leaves the marketing layer its own. */
const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-display-webfont",
  display: "swap",
  weight: ["500", "600", "700"],
});

/* JetBrains Mono was dropped with the redesign: the pack sets ALL data in the
   reader's own `ui-monospace` stack (`--font-data`), which is what its
   reference does and what removes a webfont from every page. */

export const viewport: Viewport = {
  themeColor: "#fcf9f5",
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
  const themeScript = `(function(){try{var k='${THEME_STORAGE_KEY}';var t=localStorage.getItem(k)||'light';var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);var e=document.documentElement;e.classList.toggle('dark',d);e.setAttribute('data-theme',d?'dark':'light');}catch(e){}})();`;
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${spaceGrotesk.variable} font-sans antialiased`}>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <ThemeWatcher />
        <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-2 focus:left-2 focus:px-4 focus:py-2 focus:bg-primary focus:text-primary-foreground focus:rounded-lg focus:text-sm">
          Skip to main content
        </a>
        <ClientShell>{children}</ClientShell>
      </body>
    </html>
  );
}
