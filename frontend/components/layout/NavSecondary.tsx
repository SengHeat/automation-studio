"use client";
import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  useSidebar,
} from "@/components/ui/Sidebar";
import { isNavGuardActive } from "@/lib/navigationGuard";

interface NavItem { title: string; url: string; icon: React.ElementType }

export function NavSecondary({ items }: { items: NavItem[] }) {
  const pathname = usePathname();
  const router = useRouter();
  const { open, setOpen } = useSidebar();

  function navigate(e: React.MouseEvent, url: string) {
    e.preventDefault();
    if (isNavGuardActive()) {
      const ok = window.confirm("A task is running. Leave this page and cancel it?");
      if (!ok) return;
    }
    if (window.innerWidth < 768) setOpen(false);
    router.push(url);
  }

  return (
    <SidebarGroup>
      {open && <SidebarGroupLabel>Tools</SidebarGroupLabel>}
      <SidebarMenu>
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <SidebarMenuItem key={item.title}>
              <SidebarMenuButton
                isActive={pathname === item.url}
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
