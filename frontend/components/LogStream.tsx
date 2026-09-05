"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { fileDownloadUrl, streamJob } from "@/lib/api";

const MAX_AUTO_RETRIES = 3;
const RETRY_DELAY_SEC  = 5;

interface Props {
  jobId: string | null;
  onDone?: (result?: Record<string, unknown>) => void;
}

export function LogStream({ jobId, onDone }: Props) {
  const [lines, setLines]               = useState<string[]>([]);
  const [result, setResult]             = useState<Record<string, unknown> | null>(null);
  const [done, setDone]                 = useState(false);
  const [connectionLost, setConnectionLost] = useState(false);
  const [retryCount, setRetryCount]     = useState(0);
  const [countdown, setCountdown]       = useState(0);
  const boxRef      = useRef<HTMLPreElement>(null);
  const countRef    = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopCountdown = useCallback(() => {
    if (countRef.current) { clearInterval(countRef.current); countRef.current = null; }
  }, []);

  const reconnect = useCallback(() => {
    stopCountdown();
    setConnectionLost(false);
    setCountdown(0);
    setDone(false);
    setRetryCount((n) => n + 1);
    setLines((prev) => [...prev, `🔄 Reconnecting…`]);
  }, [stopCountdown]);

  // Start countdown → auto-reconnect when countdown hits 0
  const startCountdown = useCallback(() => {
    stopCountdown();
    setCountdown(RETRY_DELAY_SEC);
    countRef.current = setInterval(() => {
      setCountdown((n) => {
        if (n <= 1) {
          clearInterval(countRef.current!);
          countRef.current = null;
          reconnect();
          return 0;
        }
        return n - 1;
      });
    }, 1000);
  }, [stopCountdown, reconnect]);

  // Subscribe / re-subscribe whenever jobId or retryCount changes
  useEffect(() => {
    if (!jobId) return;
    if (retryCount === 0) {
      setLines([]);
      setResult(null);
      setDone(false);
      setConnectionLost(false);
    }

    return streamJob(
      jobId,
      (msg) => setLines((prev) => [...prev, msg]),
      (res) => {
        stopCountdown();
        setDone(true);
        setConnectionLost(false);
        if (res) setResult(res);
        onDone?.(res);
      },
      (err) => {
        if (err === "Connection lost") {
          setConnectionLost(true);
          setLines((prev) => [...prev, `❌ Connection lost`]);
          if (retryCount < MAX_AUTO_RETRIES) {
            startCountdown();
          } else {
            setDone(true);
            setLines((prev) => [...prev, `⛔ Max retries reached. Click Reconnect to try again.`]);
          }
        } else {
          setLines((prev) => [...prev, `❌ ${err}`]);
          setDone(true);
        }
      },
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, retryCount]);

  // Cleanup countdown on unmount
  useEffect(() => () => stopCountdown(), [stopCountdown]);

  // Auto-scroll
  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [lines]);

  if (!jobId) return null;

  const path    = result?.path as string | undefined;
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

      {/* Reconnect banner */}
      {connectionLost && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-yellow-800/60 bg-yellow-950/30 px-4 py-3">
          <div className="space-y-0.5">
            <p className="text-xs font-medium text-yellow-300">
              ❌ Connection lost — job may still be running
            </p>
            {countdown > 0 && (
              <p className="text-[11px] text-yellow-600">
                Auto-reconnecting in <span className="font-mono text-yellow-400">{countdown}s</span>
                {" "}· attempt {retryCount + 1}/{MAX_AUTO_RETRIES}
              </p>
            )}
          </div>
          <button
            onClick={reconnect}
            className="shrink-0 rounded-lg bg-yellow-600 hover:bg-yellow-500 px-4 py-1.5 text-xs font-semibold text-white transition-colors"
          >
            🔄 Reconnect now
          </button>
        </div>
      )}

      {/* Manual reconnect after max retries */}
      {!connectionLost && done && retryCount >= MAX_AUTO_RETRIES && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-gray-700 bg-gray-900 px-4 py-3">
          <p className="text-xs text-gray-400">Connection could not be restored automatically.</p>
          <button
            onClick={reconnect}
            className="shrink-0 rounded-lg border border-gray-600 hover:border-gray-400 px-4 py-1.5 text-xs font-medium text-gray-300 hover:text-white transition-colors"
          >
            🔄 Try again
          </button>
        </div>
      )}

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
