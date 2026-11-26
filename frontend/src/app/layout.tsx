import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { StudioProvider } from "@/context/StudioContext";
import { EigeniaShell } from "@/components/layout/EigeniaShell";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono" });

export const metadata: Metadata = {
  title: "Eigenia // TwinScan — PuppyPi Command Center & Cyber-Physical Digital Twin Studio",
  description:
    "Unified Eigenia B.V. Mission Control for Hiwonder PuppyPi ROS 1 / ROS 2 fleet robotics, LD19 LiDAR spatial reconstruction, OpenRouter vision nameplates, PostgreSQL 18 pgvector, and Neo4j G_CPDT.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen bg-eigenia-obsidian font-sans text-eigenia-ink antialiased">
        <StudioProvider>
          <EigeniaShell>{children}</EigeniaShell>
        </StudioProvider>
      </body>
    </html>
  );
}
