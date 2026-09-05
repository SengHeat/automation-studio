"use client";
import {
  BookOpen,
  Clapperboard,
  Clock,
  FolderOpen,
  Mic,
  Video,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarTrigger,
} from "@/components/ui/Sidebar";
import { NavMain } from "./NavMain";
import { NavSecondary } from "./NavSecondary";
import { NavUser } from "./NavUser";

const mainNav = [
  { title: "Generate Story", url: "/story",   icon: BookOpen },
  { title: "Generate Voice", url: "/voice",   icon: Mic },
  { title: "Make Video",     url: "/video",   icon: Clapperboard },
  { title: "History",        url: "/history", icon: FolderOpen },
];

const secondaryNav = [
  { title: "ETA Estimator", url: "/eta", icon: Clock },
];

export function AppSidebar() {
  return (
    <Sidebar>
      <SidebarHeader>
        <div className="flex items-center gap-2.5 flex-1 min-w-0">
          <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center shrink-0">
            <Video size={14} className="text-white" />
          </div>
          <span className="font-semibold text-sm text-gray-100 truncate">Automation Studio</span>
        </div>
        <SidebarTrigger className="ml-1 shrink-0" />
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={mainNav} />
        <NavSecondary items={secondaryNav} />
      </SidebarContent>
      <NavUser />
    </Sidebar>
  );
}
