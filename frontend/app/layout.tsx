import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";
import { SidebarProvider, SidebarInset } from "@/components/ui/Sidebar";
import { AppSidebar } from "@/components/layout/AppSidebar";

const mono = Geist_Mono({ variable: "--font-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Automation Studio",
  description: "Mr.Midnight — Voice & Video Automation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full dark">
      <body className={`${mono.variable} min-h-full bg-gray-950 text-gray-100 antialiased`}>
        <SidebarProvider>
          <Suspense fallback={null}>
            <AppSidebar />
          </Suspense>
          <SidebarInset>
            <Suspense fallback={null}>
              {children}
            </Suspense>
          </SidebarInset>
        </SidebarProvider>
      </body>
    </html>
  );
}
