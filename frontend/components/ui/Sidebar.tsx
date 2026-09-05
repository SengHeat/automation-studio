"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

// ── Context ───────────────────────────────────────────────────────────────────

interface SidebarCtx { open: boolean; setOpen: (v: boolean) => void }
const Ctx = React.createContext<SidebarCtx>({ open: true, setOpen: () => {} });
export const useSidebar = () => React.useContext(Ctx);

// ── Provider ──────────────────────────────────────────────────────────────────

export function SidebarProvider({ children, className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  const [open, setOpen] = React.useState(true);

  // Close sidebar by default on mobile after mount
  React.useEffect(() => {
    if (window.innerWidth < 768) setOpen(false);
  }, []);

  return (
    <Ctx.Provider value={{ open, setOpen }}>
      <div className={cn("flex min-h-screen w-full", className)} {...props}>
        {children}
      </div>
    </Ctx.Provider>
  );
}

// ── Root Sidebar ──────────────────────────────────────────────────────────────

export function Sidebar({ className, children, ...props }: React.HTMLAttributes<HTMLElement>) {
  const { open, setOpen } = useSidebar();
  return (
    <>
      {/* Mobile backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={() => setOpen(false)}
        />
      )}
      <aside
        className={cn(
          "flex flex-col border-r border-gray-800 bg-gray-950 transition-all duration-300",
          // Mobile: fixed drawer, always w-60
          "fixed inset-y-0 left-0 z-50 w-60",
          // Desktop: relative, collapsible width
          "md:relative md:inset-auto md:z-auto",
          open ? "md:w-60" : "md:w-14",
          // Mobile translate
          open ? "translate-x-0" : "-translate-x-full md:translate-x-0",
          className,
        )}
        {...props}
      >
        {children}
      </aside>
    </>
  );
}

// ── Sections ──────────────────────────────────────────────────────────────────

export function SidebarHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-center gap-2 px-3 py-3 border-b border-gray-800", className)} {...props} />;
}

export function SidebarContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-1 flex-col overflow-y-auto py-2", className)} {...props} />;
}

export function SidebarFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-3 py-3 border-t border-gray-800", className)} {...props} />;
}

// ── Menu primitives ───────────────────────────────────────────────────────────

export function SidebarMenu({ className, ...props }: React.HTMLAttributes<HTMLUListElement>) {
  return <ul className={cn("space-y-0.5", className)} {...props} />;
}

export function SidebarMenuItem({ className, ...props }: React.HTMLAttributes<HTMLLIElement>) {
  return <li className={cn("", className)} {...props} />;
}

interface SidebarMenuButtonProps extends React.HTMLAttributes<HTMLElement> {
  size?: "sm" | "lg";
  isActive?: boolean;
  render?: React.ReactElement;
}
export function SidebarMenuButton({
  className, size = "sm", isActive, children, render, ...props
}: SidebarMenuButtonProps) {
  const { open } = useSidebar();
  const base = cn(
    "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
    "text-gray-400 hover:bg-gray-800/60 hover:text-gray-100",
    isActive && "bg-blue-600 text-white hover:bg-blue-500 hover:text-white",
    size === "lg" && "py-2.5",
    !open && "md:justify-center md:px-2",
    className,
  );
  if (render) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return React.cloneElement(render as React.ReactElement<any>, { className: base, ...props }, children);
  }
  return <button className={base} {...(props as React.ButtonHTMLAttributes<HTMLButtonElement>)}>{children}</button>;
}

// ── Group / Label ─────────────────────────────────────────────────────────────

export function SidebarGroup({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-2 py-1", className)} {...props} />;
}

export function SidebarGroupLabel({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  const { open } = useSidebar();
  if (!open) return null;
  return (
    <p className={cn("px-3 py-1.5 text-[10px] uppercase tracking-wider text-gray-600 font-semibold", className)} {...props} />
  );
}

export function SidebarGroupContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("", className)} {...props} />;
}

// ── Sub-menu ──────────────────────────────────────────────────────────────────

export function SidebarMenuSub({ className, ...props }: React.HTMLAttributes<HTMLUListElement>) {
  return <ul className={cn("ml-8 border-l border-gray-800 pl-2 space-y-0.5 mt-0.5", className)} {...props} />;
}

export function SidebarMenuSubItem({ className, ...props }: React.HTMLAttributes<HTMLLIElement>) {
  return <li className={cn("", className)} {...props} />;
}

export function SidebarMenuSubButton({
  className, isActive, ...props
}: React.AnchorHTMLAttributes<HTMLAnchorElement> & { isActive?: boolean }) {
  return (
    <a
      className={cn(
        "block rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        "text-gray-500 hover:bg-gray-800 hover:text-gray-200",
        isActive && "bg-gray-800 text-gray-200",
        className,
      )}
      {...props}
    />
  );
}

// ── Toggle / Hamburger ────────────────────────────────────────────────────────

export function SidebarTrigger({ className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const { open, setOpen } = useSidebar();
  return (
    <button
      onClick={() => setOpen(!open)}
      className={cn("rounded-md p-1.5 text-gray-500 hover:bg-gray-800 hover:text-gray-200 transition-colors", className)}
      aria-label="Toggle sidebar"
      {...props}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="3" y1="6" x2="21" y2="6" />
        <line x1="3" y1="12" x2="21" y2="12" />
        <line x1="3" y1="18" x2="21" y2="18" />
      </svg>
    </button>
  );
}

// ── Inset main area ───────────────────────────────────────────────────────────

export function SidebarInset({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return (
    <main className={cn("flex flex-1 flex-col overflow-auto min-w-0", className)} {...props} />
  );
}
