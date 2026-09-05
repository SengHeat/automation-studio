/**
 * Module-level busy flag shared between pages and NavMain.
 * Pages call setNavGuard(true) when a job starts, false when done.
 * NavMain reads isNavGuardActive() before navigating.
 */

let _active = false;

export function setNavGuard(active: boolean) {
  _active = active;
}

export function isNavGuardActive(): boolean {
  return _active;
}
