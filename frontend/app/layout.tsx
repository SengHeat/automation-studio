import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import "./globals.css";

const mono = Geist_Mono({ variable: "--font-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Automation Studio",
  description: "FilesAtNightfall — Voice & Video Automation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full dark">
      <body className={`${mono.variable} min-h-full bg-gray-950 text-gray-100 antialiased`}>
        {children}
      </body>
    </html>
  );
}
