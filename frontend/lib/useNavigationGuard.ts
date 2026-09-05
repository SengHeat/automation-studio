"use client";
import { useEffect } from "react";
import { setNavGuard } from "./navigationGuard";

/**
 * Call this in any page that runs background jobs.
 * When busy=true:
 *  - browser refresh/close shows a native "Leave site?" prompt
 *  - sidebar link clicks show a confirm dialog (handled in NavMain)
 */
export function useNavigationGuard(busy: boolean) {
  useEffect(() => {
    setNavGuard(busy);

    if (!busy) return;

    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";   // shows native browser dialog
    }

    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      setNavGuard(false);
    };
  }, [busy]);
}
