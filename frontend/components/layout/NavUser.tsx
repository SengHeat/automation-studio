"use client";
import { SidebarFooter, useSidebar } from "@/components/ui/Sidebar";

export function NavUser() {
  const { open } = useSidebar();
  return (
    <SidebarFooter>
      <div className="flex items-center gap-2.5 px-1 py-1">
        {/* Avatar */}
        <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center shrink-0">
          <span className="text-[10px] font-bold text-white">M</span>
        </div>
        {open && (
          <div className="min-w-0">
            <p className="text-xs font-medium text-gray-200 truncate">Whispered Confessions</p>
            <p className="text-[10px] text-gray-500 truncate">Free plan</p>
          </div>
        )}
      </div>
    </SidebarFooter>
  );
}
