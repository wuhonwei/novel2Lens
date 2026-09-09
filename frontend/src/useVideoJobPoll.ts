import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import { api, type Bundle, type Shot, type VideoJob } from "./api";

export type VideoBatch = { id: string; total: number };

export function videoJobResultPath(job: VideoJob): string {
  const payload = job.payload || {};
  const raw = payload.result_path ?? payload.resultPath;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  return "";
}

export function patchBundleFromVideoJobs(bundle: Bundle, jobs: VideoJob[]): Bundle | null {
  if (!jobs.length) return null;
  let shots = bundle.shots;
  let touched = false;
  for (const job of jobs) {
    const path = videoJobResultPath(job);
    const shotId = (job.shot_id || "").trim();
    if (!path || !shotId || !shots.some((s) => s.id === shotId)) return null;
    shots = shots.map((s) =>
      s.id === shotId
        ? ({
            ...s,
            video_path: path,
            video_version: (typeof s.video_version === "number" ? s.video_version : 0) + 1,
          } satisfies Shot)
        : s,
    );
    touched = true;
  }
  return touched ? { ...bundle, shots } : null;
}

export type UseVideoJobPollResult = {
  videoJobs: VideoJob[];
  setVideoJobs: Dispatch<SetStateAction<VideoJob[]>>;
  videoBatch: VideoBatch | null;
  noteVideoBatch: (batchId: string, total: number) => void;
  clearVideoBatchTracking: () => void;
  pollVideoJobsRef: MutableRefObject<(() => void) | null>;
  videoJobsActiveRef: MutableRefObject<boolean>;
};

export function useVideoJobPoll(
  projectId: string | undefined,
  seedJobs: VideoJob[] | undefined,
  getBundle: () => Bundle | null,
  setBundle: (bundle: Bundle) => void,
): UseVideoJobPollResult {
  const [videoJobs, setVideoJobs] = useState<VideoJob[]>([]);
  const [videoBatch, setVideoBatch] = useState<VideoBatch | null>(null);
  const videoJobsActiveRef = useRef(false);
  const prevActiveCountRef = useRef(0);
  const videoBatchRef = useRef<VideoBatch | null>(null);
  const pollVideoJobsRef = useRef<(() => void) | null>(null);
  const prevJobsRef = useRef<VideoJob[]>([]);
  const getBundleRef = useRef(getBundle);
  const setBundleRef = useRef(setBundle);
  getBundleRef.current = getBundle;
  setBundleRef.current = setBundle;

  function noteVideoBatch(batchId: string, total: number) {
    const next = { id: batchId, total: Math.max(total, 1) };
    videoBatchRef.current = next;
    setVideoBatch(next);
    queueMicrotask(() => pollVideoJobsRef.current?.());
  }

  function clearVideoBatchTracking() {
    setVideoBatch(null);
    videoBatchRef.current = null;
    videoJobsActiveRef.current = false;
    prevActiveCountRef.current = 0;
  }

  useEffect(() => {
    if (!projectId) {
      setVideoJobs([]);
      setVideoBatch(null);
      videoBatchRef.current = null;
      videoJobsActiveRef.current = false;
      prevActiveCountRef.current = 0;
      prevJobsRef.current = [];
      return;
    }
    const pid = projectId;
    let stop = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    function shouldKeepPolling(jobs: VideoJob[]) {
      return jobs.length > 0 || videoBatchRef.current !== null;
    }

    function syncInterval(jobs: VideoJob[]) {
      if (stop) return;
      if (shouldKeepPolling(jobs) && !timer) {
        timer = window.setInterval(() => {
          void poll();
        }, 2000);
      } else if (!shouldKeepPolling(jobs) && timer) {
        window.clearInterval(timer);
        timer = null;
      }
    }

    async function refreshAfterFinish(activeJobs: VideoJob[], prevJobs: VideoJob[]) {
      const activeIds = new Set(activeJobs.map((j) => j.id));
      const disappeared = prevJobs.filter((j) => !activeIds.has(j.id));
      const current = getBundleRef.current();
      if (!current || !disappeared.length) {
        const next = await api.get(pid);
        if (!stop) setBundleRef.current(next);
        return;
      }
      let candidates: VideoJob[] = [];
      try {
        const { jobs: recent } = await api.listVideoJobs(pid, false);
        if (stop) return;
        const byId = new Map(recent.map((j) => [j.id, j]));
        candidates = disappeared
          .map((j) => byId.get(j.id))
          .filter((j): j is VideoJob => !!j && j.status === "succeeded");
      } catch {
        candidates = [];
      }
      const canPatch =
        candidates.length === disappeared.length && candidates.every((j) => videoJobResultPath(j));
      if (canPatch) {
        const patched = patchBundleFromVideoJobs(current, candidates);
        if (patched) {
          if (!stop) setBundleRef.current(patched);
          return;
        }
      }
      const next = await api.get(pid);
      if (!stop) setBundleRef.current(next);
    }

    async function poll() {
      try {
        const { jobs } = await api.listVideoJobs(pid, true);
        if (stop) return;
        const prev = prevActiveCountRef.current;
        const prevJobs = prevJobsRef.current;
        setVideoJobs(jobs);
        prevActiveCountRef.current = jobs.length;
        prevJobsRef.current = jobs;
        if (jobs.length > 0) {
          videoJobsActiveRef.current = true;
          if (!videoBatchRef.current) {
            const bid = jobs.find((j) => j.batch_id)?.batch_id || "";
            if (bid) noteVideoBatch(bid, jobs.length);
          }
        }
        const finishedSome = videoJobsActiveRef.current && jobs.length < prev;
        const finishedAll = videoJobsActiveRef.current && jobs.length === 0;
        if (finishedSome || finishedAll) {
          await refreshAfterFinish(jobs, prevJobs);
          if (stop) return;
        }
        if (finishedAll) {
          videoJobsActiveRef.current = false;
          videoBatchRef.current = null;
          setVideoBatch(null);
        }
        syncInterval(jobs);
      } catch {
        /* keep last */
      }
    }

    pollVideoJobsRef.current = () => {
      void poll();
    };

    if (seedJobs?.length) {
      setVideoJobs(seedJobs);
      videoJobsActiveRef.current = true;
      prevActiveCountRef.current = seedJobs.length;
      prevJobsRef.current = seedJobs;
    }

    void poll();
    return () => {
      stop = true;
      pollVideoJobsRef.current = null;
      if (timer) window.clearInterval(timer);
    };
  }, [projectId]);

  return {
    videoJobs,
    setVideoJobs,
    videoBatch,
    noteVideoBatch,
    clearVideoBatchTracking,
    pollVideoJobsRef,
    videoJobsActiveRef,
  };
}
