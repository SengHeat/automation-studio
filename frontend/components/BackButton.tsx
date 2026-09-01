import Link from "next/link";

export function BackButton() {
  return (
    <Link
      href="/"
      className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-white transition-colors mb-6"
    >
      ← Back to Menu
    </Link>
  );
}
