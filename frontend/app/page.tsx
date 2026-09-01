import Link from "next/link";

const MENU = [
  { href: "/story",   icon: "✍️", label: "Generate Story",  desc: "AI creates full story JSON" },
  { href: "/studio",  icon: "🎙", label: "Generate Voice",  desc: "TTS narration pipeline" },
  { href: "/studio",  icon: "🎬", label: "Make Video",      desc: "Voice + cinematic renderer" },
  { href: "/eta",     icon: "⏱", label: "ETA Duration",    desc: "Estimate script reading time" },
  { href: "/convert", icon: "📝", label: "Text → JSON",     desc: "Convert plain text to story" },
  { href: "/history", icon: "📂", label: "History",         desc: "Browse & manage saved files" },
  { href: "/youtube", icon: "📺", label: "YouTube Upload",  desc: "OAuth + direct video upload" },
  { href: "/queue",   icon: "🚀", label: "Batch Queue",     desc: "Overnight multi-story render" },
];

export default function Home() {
  return (
    <main className="min-h-screen p-8 max-w-5xl mx-auto">
      <div className="mb-10">
        <h1 className="text-3xl font-bold text-white mb-1">🎙 FilesAtNightfall</h1>
        <p className="text-gray-400">Automation Studio — choose a tool to get started</p>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {MENU.map((item) => (
          <Link
            key={item.label}
            href={item.href}
            className="group flex flex-col gap-2 p-5 rounded-xl border border-gray-800
                       bg-gradient-to-br from-gray-900 to-gray-950
                       hover:border-blue-500 hover:shadow-lg hover:shadow-blue-500/10
                       transition-all duration-200 hover:-translate-y-0.5"
          >
            <span className="text-3xl">{item.icon}</span>
            <span className="font-semibold text-white text-sm">{item.label}</span>
            <span className="text-xs text-gray-400 leading-relaxed">{item.desc}</span>
          </Link>
        ))}
      </div>
    </main>
  );
}
