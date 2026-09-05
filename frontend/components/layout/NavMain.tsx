"use client";
import * as React from "react";
import { usePathname, useSearchParams, useRouter } from "next/navigation";
import { ChevronRight } from "lucide-react";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  useSidebar,
} from "@/components/ui/Sidebar";
import { isNavGuardActive } from "@/lib/navigationGuard";

interface NavSubItem { title: string; url: string }
interface NavItem { title: string; url: string; icon: React.ElementType; items?: NavSubItem[] }

export function NavMain({ items }: { items: NavItem[] }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { open, setOpen } = useSidebar();
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({});

  function matchesUrl(url: string) {
    const [urlPath, urlQuery] = url.split("?");
    if (pathname !== urlPath) return false;
    if (!urlQuery) return true;
    const urlParams = new URLSearchParams(urlQuery);
    for (const [k, v] of urlParams.entries()) {
      if (searchParams.get(k) !== v) return false;
    }
    return true;
  }

  function navigate(e: React.MouseEvent, url: string) {
    e.preventDefault();
    if (isNavGuardActive()) {
      const ok = window.confirm("A task is running. Leave this page and cancel it?");
      if (!ok) return;
    }
    // Close sidebar drawer on mobile after navigating
    if (window.innerWidth < 768) setOpen(false);
    router.push(url);
  }

  return (
    <SidebarGroup>
      <SidebarGroupLabel>Platform</SidebarGroupLabel>
      <SidebarMenu>
        {items.map((item) => {
          const Icon = item.icon;
          const isActive =
            matchesUrl(item.url) ||
            (item.items?.some((sub) => matchesUrl(sub.url)) ?? false);
          const isOpen = expanded[item.title] ?? false;

          if (item.items && item.items.length > 0) {
            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  isActive={isActive}
                  onClick={() => setExpanded(p => ({ ...p, [item.title]: !p[item.title] }))}
                  title={item.title}
                >
                  <Icon size={16} />
                  {open && (
                    <>
                      <span className="flex-1">{item.title}</span>
                      <ChevronRight size={14} className={`ml-auto transition-transform ${isOpen ? "rotate-90" : ""}`} />
                    </>
                  )}
                </SidebarMenuButton>
                {isOpen && open && (
                  <ul className="ml-8 border-l border-gray-800 pl-2 space-y-0.5 mt-0.5">
                    {item.items.map(sub => (
                      <li key={sub.title}>
                        <a
                          href={sub.url}
                          onClick={e => navigate(e, sub.url)}
                          className={`block rounded-md px-3 py-1.5 text-xs font-medium transition-colors
                            ${pathname === sub.url ? "bg-gray-800 text-gray-200" : "text-gray-500 hover:bg-gray-800 hover:text-gray-200"}`}>
                          {sub.title}
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </SidebarMenuItem>
            );
          }

          return (
            <SidebarMenuItem key={item.title}>
              <SidebarMenuButton
                isActive={isActive}
                render={<a href={item.url} onClick={e => navigate(e, item.url)} />}
                title={item.title}
              >
                <Icon size={16} />
                {open && <span>{item.title}</span>}
              </SidebarMenuButton>
            </SidebarMenuItem>
          );
        })}
      </SidebarMenu>
    </SidebarGroup>
  );
}
