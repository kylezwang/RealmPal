import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "800"],
});
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "800"],
});

export const metadata: Metadata = {
  title: "RealmPal | Your RotMG AI Companion",
  description: "AI-powered Realm of the Mad God companion. Look up players, guilds, items, and dungeon strategies.",
  openGraph: {
    title: "RealmPal",
    description: "Your RotMG AI companion powered by Claude",
    siteName: "RealmPal",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#1a1a1a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}
        style={{ backgroundColor: "#1a1a1a", color: "#ececec" }}>
        {children}
      </body>
    </html>
  );
}
