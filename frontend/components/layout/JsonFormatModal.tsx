"use client";
import { useState } from "react";
import { X, ChevronDown, ChevronRight } from "lucide-react";

type Section = {
  id: string;
  title: string;
  kh: string;
  content: string;
};

const SECTIONS: Section[] = [
  {
    id: "overview",
    title: "📁 រចនាសម្ព័ន្ធទូទៅ — Top-Level Structure",
    kh: "ឯកសារ JSON មានផ្នែកចំនួន ៤ ដែលត្រូវដាក់នៅខាងក្រៅបំផុត:",
    content: `{
  "project":  { ... },   ← ព័ត៌មានអំពីវីដេអូ (metadata)
  "starting": { ... },   ← អត្ថបទណែនាំ (លេង​មុន​គេ) — optional
  "stories":  [ ... ],   ← រឿងភ័យ ១ ឬច្រើន
  "ending":   { ... }    ← អត្ថបទ​បិទ / end screen — optional
}`,
  },
  {
    id: "project",
    title: "🎬 project — ព័ត៌មានអំពីវីដេអូ",
    kh: 'ផ្នែក "project" ផ្ទុកព័ត៌មានទូទៅអំពីវីដេអូ។ Key សំខាន់ៗ:',
    content: `"project": {
  "title":             ← ឈ្មោះផ្ទៃក្នុង (បង្ហាញក្នុង Studio History)
  "youtube_title":     ← ចំណងជើងសំរាប់ YouTube
  "thumbnail_text":    ← អក្សរជាក់លក់​លើ Thumbnail
  "channel":           ← ឈ្មោះ Channel (watermark លើវីដេអូ)
  "voice_model":       ← AI សំឡេង — ប្រើ "VoxCPM2"
  "narration_notes":   ← ណែនាំ​ស្ទីល​ការ​និយាយ ប្រគល់ ​ទៅ​ AI
  "story_count":       ← ចំនួនរឿង
  "segment_count":     ← ចំនួន segment សរុប
  "status":            ← "draft" ឬ "ready"
}`,
  },
  {
    id: "starting",
    title: "🎙 starting — អត្ថបទណែនាំ (Intro)",
    kh: 'ផ្នែក "starting" គឺ segment ដំបូងបំផុតក្នុងវីដេអូ — លេង​មុន​រឿង​ទី ១។ ប្រើ​សម្រាប់​ "hook" ទាក់​ចិត្ត​អ្នក​មើល។',
    content: `"starting": {
  "title":         ← ស្លាក​ (ឧ. "Intro") — បង្ហាញ​ក្នុង logs
  "duration":      ← រយៈ​ពេល​ប៉ាន់​ស្មាន — "0:00-0:30"
  "visual_prompt": ← ពណ៌នា​រូបភាព​ / វីដេអូ​ Background
  "narration":     ← អត្ថបទ​ (ត្រូវ​ AI និយាយ)
}

⚠ ចំណាំ: ប្រសិន​បើ​មិន​ដាក់ "starting" នោះ​រឿង​ទី ១ segment ទី ១
  នឹង​លេង​ដំបូង​ជំនួស​វិញ។`,
  },
  {
    id: "stories",
    title: "📖 stories — អារ៉េ​រឿង",
    kh: '"stories" គឺ​ array ដែល​ផ្ទុក​រឿង​ម្នាក់​ ឬ​ច្រើន។ Key សំខាន់ₓ​ក្នុង​រឿង​នីមួយៗ:',
    content: `"stories": [
  {
    "story_number":       ← លំដាប់​រឿង (1, 2, 3...)
    "title":              ← ឈ្មោះ​ខ្លី​របស់​រឿង
    "estimated_duration": ← ពេល​វេលា​ប៉ាន់​ (ឧ. "0:00-8:13")
    "youtube_title":      ← ចំណងជើង​ chapter YouTube
    "characters":         ← [ "Narrator", "Noah" ] — list​ តួអង្គ
    "viewer_question":    ← CTA comment ទុក​ចុង​រឿង
    "segments": [ ... ]   ← segments​ ក្នុង​រឿង​នេះ (សូមមើល​ខាងក្រោម)
  }
]`,
  },
  {
    id: "segment",
    title: "🎞 segment — ឯកតា​និយាយ​តូចមួយ",
    kh: "Segment​ គ្រប់​ segment ជា​ chunk​ ខ្លី​មួយ​ — narration ១​ ដំណក់​ + វីដេអូ​ background ១​ ចំណែក។",
    content: `{
  "segment":       ← លេខ​ segment ក្នុង​រឿង (1, 2, 3...)
  "duration":      ← ពេល​វេលា​ "MM:SS-MM:SS" — ប្រើ​ align​ ជាមួយ​ voice
  "visual_prompt": ← ពណ៌នា​ footage — AI / Pexels ស្វែង​រក​ជូន
  "narration":     ← អត្ថបទ​ text ដែល​ AI សំឡេង​ (VoxCPM2) នឹង​និយាយ

  --- Optional ---
  "stock_query":        ← Override Pexels search term ប្រសិន​ auto result​ ខុស
  "control_instruction":← Override ស្ទីល​ narration​ segment​ នេះ​ (ជំនួស project.narration_notes)
  "image_or_video":     ← Path ឬ URL ត្រង់​ → skip​ ការ​ download​ stock​ ទាំង​ស្រុង
}

💡 Tips:
  • Segment ១​ មិន​គួរ​លើស​ ~90 វិនាទី​ narration
  • visual_prompt​ ល្អ: "Close-up of a dark hallway, single lamp flickering"
  • visual_prompt​ អន់: "Part where the lights go off"`,
  },
  {
    id: "ending",
    title: "🎬 ending — End Screen Narration",
    kh: '"ending" គឺ​ segment ចុងក្រោយ​ — ត្រូវ​ប្រើ​សម្រាប់​ recap + CTA "watch next" ឬ "subscribe"។',
    content: `"ending": {
  "title":         ← ស្លាក (ឧ. "End Screen")
  "duration":      ← ពេល​វេលា​ប៉ាន់​ (ឧ. "26:23-28:16")
  "visual_prompt": ← ពណ៌នា​ footage​ ចុង​ (ឧ. "dark hallway fading to black")
  "narration":     ← អត្ថបទ​បិទ​ + CTA
}

⚠ ចំណាំ: YouTube End Screen cards (ប៊ូតុង​ clickable) ដាក់​ដោយ​ដៃ​
  ក្នុង YouTube Studio — ending​ នេះ​គ្រាន់​តែ​ narration + background​ footage។`,
  },
  {
    id: "order",
    title: "🔢 លំដាប់​ Render",
    kh: "ចំណុចនេះ​ ពន្យល់​ ថា​ Segment​ ត្រូវ​បាន​ render​ តាម​លំដាប់​ណា:",
    content: `[starting]  →  [story 1 segments]  →  [story 2 segments]
            →  [story 3 segments]  →  [ending]

• starting  — optional, ប្រសិន​ absent → លើស
• stories   — required, ត្រូវ​មាន​ segments យ៉ាង​ហោច ១
• ending    — optional, ប្រសិន​ absent → លើស`,
  },
  {
    id: "example",
    title: "✅ ឧទាហរណ៍​ JSON​ ពេញ​",
    kh: "JSON​ ខាងក្រោម​ គ្រប់​ field​ — copy-paste ហើយ​ edit narration​ ប៉ុណ្ណោះ:",
    content: `{
  "project": {
    "title": "1 True Horror Story",
    "channel": "Whispered Confessions",
    "voice_model": "VoxCPM2",
    "narration_notes": "Slow, calm, first-person horror delivery.",
    "status": "draft"
  },

  "starting": {
    "title": "Intro",
    "duration": "0:00-0:20",
    "visual_prompt": "A quiet suburban street at night.",
    "narration": "What I am about to tell you happened in my own home."
  },

  "stories": [
    {
      "story_number": 1,
      "title": "The Upstairs Room",
      "segments": [
        {
          "segment": 1,
          "duration": "0:20-1:00",
          "visual_prompt": "Empty bedroom, single lamp on, curtains closed.",
          "narration": "The house had been empty for six months before we moved in."
        },
        {
          "segment": 2,
          "duration": "1:00-1:45",
          "visual_prompt": "A dark staircase leading up to a closed door.",
          "narration": "On our third night, I heard footsteps from directly above."
        }
      ]
    }
  ],

  "ending": {
    "title": "End Screen",
    "duration": "1:45-2:15",
    "visual_prompt": "Dark hallway fading to black.",
    "narration": "If this kept you up tonight, the next one is worse. Watch it here."
  }
}`,
  },
];

export function JsonFormatModal({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState<Record<string, boolean>>({
    overview: true,
  });

  const toggle = (id: string) =>
    setOpen((prev) => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="flex-1 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer — 40% width, slides in from the right */}
      <div
        className="w-[40%] min-w-[320px] h-full bg-[#0f1117] border-l border-gray-800 flex flex-col shadow-2xl
                   animate-[slideInRight_0.25s_ease-out]"
        style={{ animation: "slideInRight 0.25s ease-out" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 shrink-0">
          <div>
            <h2 className="text-base font-semibold text-white">
              📄 Story JSON Format Guide
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              ការណែនាំ​ទ្រង់ទ្រាយ JSON — Whispered Confessions
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white transition-colors p-1"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-4 py-4 space-y-2">
          {SECTIONS.map((sec) => (
            <div
              key={sec.id}
              className="border border-gray-800 rounded-lg overflow-hidden"
            >
              <button
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-800/50 transition-colors"
                onClick={() => toggle(sec.id)}
              >
                <span className="text-sm font-medium text-gray-200">
                  {sec.title}
                </span>
                {open[sec.id] ? (
                  <ChevronDown size={15} className="text-gray-500 shrink-0" />
                ) : (
                  <ChevronRight size={15} className="text-gray-500 shrink-0" />
                )}
              </button>

              {open[sec.id] && (
                <div className="px-4 pb-4 space-y-3 bg-gray-900/30">
                  <p className="text-sm text-blue-300 leading-relaxed pt-2">
                    {sec.kh}
                  </p>
                  <pre className="text-xs text-green-300 bg-black/50 rounded-lg p-3 overflow-x-auto leading-relaxed whitespace-pre-wrap font-mono border border-gray-800">
                    {sec.content}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-800 shrink-0 flex justify-between items-center">
          <p className="text-[11px] text-gray-600">
            ចុច​ section​ ដើម្បី​ expand / collapse
          </p>
          <button
            onClick={onClose}
            className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-200 px-4 py-1.5 rounded-lg transition-colors"
          >
            បិទ​ / Close
          </button>
        </div>
      </div>

      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
      `}</style>
    </div>
  );
}
