import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import { api, type Asset, type Bundle, type ImageJob, type Shot } from "./api";

export type ImageBatch = { id: string; total: number };

const ASSET_PATH_FIELD: Record<string, keyof Asset> = {
  half: "half_path",
  full: "full_path",
  far: "far_path",
  near: "near_path",
  image: "image_path",
};

/** Read written media path from a finished job payload (or top-level). */
export function jobResultPath(job: ImageJob): string {
  const payload = job.payload || {};
  const raw = payload.result_path ?? payload.resultPath;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  return "";
}

/**
 * Merge result_path from finished jobs into local assets/shots.
 * Returns null when any candidate lacks a usable path/target — caller should full-reload.
 */
export function patchBundleFromJobResults(bundle: Bundle, jobs: ImageJob[]): Bundle | null {
  if (!jobs.length) return null;

  let assets = bundle.assets;
  let shots = bundle.shots;
  let touched = false;

  for (const job of jobs) {
    const path = jobResultPath(job);
    const field = (job.target_field || "").trim();
    if (!path || !field) return null;

    if (field === "first_frame") {
      const shotId =
        (job.shot_id || "").trim() ||
        (typeof job.payload?.shot_id === "string" ? job.payload.shot_id.trim() : "") ||
        (job.asset_id || "").trim();
      if (!shotId || !shots.some((s) => s.id === shotId)) return null;
      shots = shots.map((s) =>
        s.id === shotId
          ? ({
              ...s,
              first_frame_path: path,
              first_frame_unready: false,
              // Same file path is overwritten on disk — bump so <img> reloads.
              first_frame_version:
                (typeof s.first_frame_version === "number" ? s.first_frame_version : 0) + 1,
            } satisfies Shot)
          : s,
      );
      touched = true;
      continue;
    }

    const assetKey = ASSET_PATH_FIELD[field];
    if (!assetKey) return null;
    const assetId = (job.asset_id || "").trim();
    if (!assetId || !assets.some((a) => a.id === assetId)) return null;
    assets = assets.map((a) => {
      if (a.id !== assetId) return a;
      const next: Asset = { ...a, [assetKey]: path };
      next.media_version = (typeof a.media_version === "number" ? a.media_version : 0) + 1;
      return next;
    });
    touched = true;
  }

  return touched ? { ...bundle, assets, shots } : null;
}

export type UseImageJobPollResult = {
  imageJobs: ImageJob[];
  setImageJobs: Dispatch<SetStateAction<ImageJob[]>>;
  imageBatch: ImageBatch | null;
  setImageBatch: Dispatch<SetStateAction<ImageBatch | null>>;
  imageJobsActiveRef: MutableRefObject<boolean>;
  prevActiveCountRef: MutableRefObject<number>;
  imageBatchRef: MutableRefObject<ImageBatch | null>;
  pollImageJobsRef: MutableRefObject<(() => void) | null>;
  noteImageBatch: (batchId: string, total: number) => void;
  clearBatchTracking: () => void;
};

/**
 * Poll active image jobs for the open project; on finish, prefer local path patches
 * from job payloads, else fall back to full project GET.
 */
export function useImageJobPoll(
  projectId: string | undefined,
  seedJobs: ImageJob[] | undefined,
  getBundle: () => Bundle | null,
  setBundle: (bundle: Bundle) => void,
): UseImageJobPollResult {
  const [imageJobs, setImageJobs] = useState<ImageJob[]>([]);
  const [imageBatch, setImageBatch] = useState<ImageBatch | null>(null);
  const imageJobsActiveRef = useRef(false);
  const prevActiveCountRef = useRef(0);
  const imageBatchRef = useRef<ImageBatch | null>(null);
  const pollImageJobsRef = useRef<(() => void) | null>(null);
  const prevJobsRef = useRef<ImageJob[]>([]);
  const getBundleRef = useRef(getBundle);
  const setBundleRef = useRef(setBundle);
  getBundleRef.current = getBundle;
  setBundleRef.current = setBundle;

  function noteImageBatch(batchId: string, total: number) {
    const next = { id: batchId, total: Math.max(total, 1) };
    imageBatchRef.current = next;
    setImageBatch(next);
    // Jobs were often empty before enqueue, so the poll interval is stopped.
    // Kick once so completion is detected and the UI refreshes.
    queueMicrotask(() => pollImageJobsRef.current?.());
  }

  function clearBatchTracking() {
    setImageBatch(null);
    imageBatchRef.current = null;
    imageJobsActiveRef.current = false;
    prevActiveCountRef.current = 0;
  }

  useEffect(() => {
    if (!projectId) {
      setImageJobs([]);
      setImageBatch(null);
      imageBatchRef.current = null;
      imageJobsActiveRef.current = false;
      prevActiveCountRef.current = 0;
      prevJobsRef.current = [];
      return;
    }
    const pid = projectId;
    let stop = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    function shouldKeepPolling(jobs: ImageJob[]) {
      return jobs.length > 0 || imageBatchRef.current !== null;
    }

    function syncInterval(jobs: ImageJob[]) {
      if (stop) return;
      if (shouldKeepPolling(jobs) && !timer) {
        timer = window.setInterval(() => {
          void poll();
        }, 1500);
      } else if (!shouldKeepPolling(jobs) && timer) {
        window.clearInterval(timer);
        timer = null;
      }
    }

    async function refreshBundleAfterFinish(activeJobs: ImageJob[], prevJobs: ImageJob[]) {
      const activeIds = new Set(activeJobs.map((j) => j.id));
      const disappeared = prevJobs.filter((j) => !activeIds.has(j.id));
      const current = getBundleRef.current();
      if (!current) {
        const next = await api.get(pid);
        if (!stop) setBundleRef.current(next);
        return;
      }

      // Without a clear set of just-finished jobs, prefer a full reload.
      if (!disappeared.length) {
        const next = await api.get(pid);
        if (!stop) setBundleRef.current(next);
        return;
      }

      // Prefer patching from finished jobs that carry result_path in payload.
      let candidates: ImageJob[] = [];
      try {
        const { jobs: recent } = await api.listImageJobs(pid, false);
        if (stop) return;
        const byId = new Map(recent.map((j) => [j.id, j]));
        candidates = disappeared
          .map((j) => byId.get(j.id))
          .filter((j): j is ImageJob => !!j && j.status === "succeeded");
      } catch {
        candidates = [];
      }

      const canPatch =
        candidates.length === disappeared.length && candidates.every((j) => jobResultPath(j));

      if (canPatch) {
        const patched = patchBundleFromJobResults(current, candidates);
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
        const { jobs } = await api.listImageJobs(pid, true);
        if (stop) return;
        const prev = prevActiveCountRef.current;
        const prevJobs = prevJobsRef.current;
        setImageJobs(jobs);
        prevActiveCountRef.current = jobs.length;
        prevJobsRef.current = jobs;
        if (jobs.length > 0) {
          imageJobsActiveRef.current = true;
          if (!imageBatchRef.current) {
            const bid = jobs.find((j) => j.batch_id)?.batch_id || "";
            if (bid) noteImageBatch(bid, jobs.length);
          } else if (jobs.length > imageBatchRef.current.total) {
            noteImageBatch(imageBatchRef.current.id, jobs.length);
          }
        }
        const finishedSome = imageJobsActiveRef.current && jobs.length < prev;
        const finishedAll = imageJobsActiveRef.current && jobs.length === 0;
        if (finishedSome || finishedAll) {
          await refreshBundleAfterFinish(jobs, prevJobs);
          if (stop) return;
        }
        if (finishedAll) {
          imageJobsActiveRef.current = false;
          imageBatchRef.current = null;
          setImageBatch(null);
        }
        // Keep polling while local batch tracking is still open even if first poll raced.
        syncInterval(jobs);
      } catch {
        /* keep last known jobs */
      }
    }

    pollImageJobsRef.current = () => {
      void poll();
    };

    if (seedJobs?.length) {
      setImageJobs(seedJobs);
      imageJobsActiveRef.current = true;
      prevActiveCountRef.current = seedJobs.length;
      prevJobsRef.current = seedJobs;
    }

    void poll();
    return () => {
      stop = true;
      pollImageJobsRef.current = null;
      if (timer) window.clearInterval(timer);
    };
    // Seed jobs only when the project id changes.
  }, [projectId]);

  return {
    imageJobs,
    setImageJobs,
    imageBatch,
    setImageBatch,
    imageJobsActiveRef,
    prevActiveCountRef,
    imageBatchRef,
    pollImageJobsRef,
    noteImageBatch,
    clearBatchTracking,
  };
}
