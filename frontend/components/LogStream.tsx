"use client";
import {useEffect, useRef, useState} from "react";
import {fileDownloadUrl, streamJob} from "@/lib/api";

interface Props {
  jobId: string | null;
  onDone?: (result?: Record<string, unknown>) => void;
}

export function LogStream({ jobId, onDone }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [done, setDone] = useState(false);
  const boxRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (!jobId) return;
    setLines([]);
    setResult(null);
    setDone(false);

    return streamJob(
        jobId,
        (msg) => setLines((prev) => [...prev, msg]),
        (res) => {
          setDone(true);
          if (res) setResult(res);
          onDone?.(res);
        },
        (err) => {
          setLines((prev) => [...prev, `❌ ${err}`]);
          setDone(true);
        },
    );
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll
  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [lines]);

  if (!jobId) return null;

  const path = result?.path as string | undefined;
  const isAudio = path?.match(/\.(mp3|wav|ogg)$/i);
  const isVideo = path?.match(/\.mp4$/i);
  const isSrt   = path?.match(/\.srt$/i);

  return (
    <div className="mt-4 space-y-3">
      <pre
        ref={boxRef}
        className="h-56 overflow-y-auto rounded-lg border border-gray-800 bg-gray-950
                   p-3 text-xs text-gray-300 font-mono whitespace-pre-wrap"
      >
        {lines.join("\n") || "Starting…"}
      </pre>

      {done && path && (
        <div className="rounded-lg border border-gray-700 bg-gray-900 p-4 space-y-2">
          {isAudio && (
            <audio controls src={fileDownloadUrl(path)} className="w-full" />
          )}
          {isVideo && (
            <video controls src={fileDownloadUrl(path)} className="w-full rounded" />
          )}
          <a
            href={fileDownloadUrl(path)}
            download
            className="inline-block text-xs text-blue-400 hover:underline"
          >
            ⬇ Download {path.split("/").pop()}
          </a>
        </div>
      )}

      {done && !!result?.json && (
        <details className="rounded-lg border border-gray-700">
          <summary className="cursor-pointer px-3 py-2 text-xs text-gray-400 hover:text-gray-200">
            View JSON preview
          </summary>
          <pre className="max-h-72 overflow-y-auto p-3 text-xs text-green-300 font-mono">
            {JSON.stringify(result.json as object, null, 2)}
          </pre>
        </details>
      )}

      {done && typeof result?.chapters === "string" && result.chapters && (
        <div>
          <p className="mb-1 text-xs text-gray-400">Chapter markers — paste into YouTube description:</p>
          <textarea
            readOnly
            value={result.chapters}
            rows={8}
            className="w-full rounded border border-gray-700 bg-gray-900 p-2 text-xs font-mono text-gray-200"
          />
        </div>
      )}
    </div>
  );
}
