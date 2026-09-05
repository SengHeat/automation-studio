"use client";
import { useState } from "react";
import { SidebarFooter, useSidebar } from "@/components/ui/Sidebar";
import { JsonFormatModal } from "./JsonFormatModal";

export function NavUser() {
  const { open } = useSidebar();
  const [showModal, setShowModal] = useState(false);

  return (
    <>
      <SidebarFooter>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2.5 px-1 py-1 w-full rounded-lg hover:bg-gray-800/60 transition-colors text-left"
          title="View JSON Format Guide"
        >
          {/* Avatar */}
          <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center shrink-0">
            <span className="text-[10px] font-bold text-white">W</span>
          </div>
          {open && (
            <div className="min-w-0">
              <p className="text-xs font-medium text-gray-200 truncate">Whispered Confessions</p>
              <p className="text-[10px] text-gray-500 truncate">JSON Format Guide →</p>
            </div>
          )}
        </button>
      </SidebarFooter>

      {showModal && <JsonFormatModal onClose={() => setShowModal(false)} />}
    </>
  );
}
