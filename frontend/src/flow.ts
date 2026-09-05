import type { Asset, Bundle, Chapter, Shot } from "./api";
import { normalizeKind } from "./api";

export type TabName = "原文" | "全书资产" | "分镜";

export type FlowStepId =
  | "style"
  | "generate_assets"
  | "upload"
  | "storyboard"
  | "review"
  | "export"
  | "next_chapter";

export type FlowGuide = {
  step: FlowStepId;
  index: number;
  title: string;
  tip: string;
  cta: string;
  tab?: TabName;
};

const PIPELINE = [
  { id: "style", label: "画风" },
  { id: "generate_assets", label: "全书资产" },
  { id: "upload", label: "上传图" },
  { id: "storyboard", label: "分镜" },
  { id: "review", label: "校对" },
  { id: "export", label: "导出" },
] as const;

export function pipelineSteps() {
  return PIPELINE;
}

function missingRefCount(assets: Asset[]): number {
  let n = 0;
  for (const a of assets) {
    const kind = normalizeKind(a.kind);
    if (kind === "character") {
      if (!a.half_path || !a.full_path) n += 1;
    } else if (kind === "scene") {
      if (!(a.near_path || a.far_path || a.image_path)) n += 1;
    } else if (!a.image_path) {
      n += 1;
    }
  }
  return n;
}

export function bookAssetsReady(bundle: Bundle): boolean {
  const chars = bundle.assets.filter((a) => normalizeKind(a.kind) === "character");
  return chars.length > 0 && chars.every((a) => a.confirmed);
}

export function assetsByKind(bundle: Bundle) {
  const characters = bundle.assets.filter((a) => normalizeKind(a.kind) === "character");
  const scenes = bundle.assets.filter((a) => normalizeKind(a.kind) === "scene");
  const props = bundle.assets.filter((a) => normalizeKind(a.kind) === "prop");
  return { characters, scenes, props };
}

export function deriveGuide(bundle: Bundle, chapter: Chapter | undefined, shots: Shot[]): FlowGuide {
  const styleOk = Boolean((bundle.project.style || "").trim());
  if (!styleOk) {
    return {
      step: "style",
      index: 0,
      title: "第 1 步 · 填写项目画风",
      tip: "画风会注入资产描述和首帧提示词。",
      cta: "保存画风设置",
    };
  }

  if (!bookAssetsReady(bundle)) {
    return {
      step: "generate_assets",
      index: 1,
      title: "第 2 步 · 一键生成全书资产",
      tip: "对整本 TXT 扫描两遍以上：人物形象、核心场景、核心物品。无需按章确认。",
      cta: "一键生成全书资产",
      tab: "全书资产",
    };
  }

  const missing = missingRefCount(bundle.assets);
  if (missing > 0 && (!chapter || chapter.status !== "storyboarded")) {
    return {
      step: "upload",
      index: 2,
      title: "第 3 步 · 上传参考图（建议）",
      tip: `还有 ${missing} 个全书资产缺图。人物需半身+全身，场景/物品各一张。可先生成分镜，缺图镜会标「首帧未就绪」。`,
      cta: "去全书资产补图",
      tab: "全书资产",
    };
  }

  if (!chapter) {
    return {
      step: "storyboard",
      index: 3,
      title: "选择章节生成分镜",
      tip: "左侧选择章节，直接生成分镜（资产已按全书登记）。",
      cta: "选择章节",
      tab: "原文",
    };
  }

  if (chapter.status !== "storyboarded") {
    return {
      step: "storyboard",
      index: 3,
      title: "第 4 步 · 生成本章分镜",
      tip: `使用全书资产表切镜：「${chapter.title}」。无需再确认本章资产。`,
      cta: "生成本章分镜",
      tab: "原文",
    };
  }

  const unready = shots.filter((s) => s.first_frame_unready).length;
  if (unready > 0 || missing > 0) {
    return {
      step: "review",
      index: 4,
      title: "第 5 步 · 校对分镜与补图",
      tip: unready
        ? `有 ${unready} 个镜头首帧未就绪（多半缺参考图）。补图后可再导出。`
        : "分镜已生成，可微调提示词后导出。",
      cta: unready || missing ? "去全书资产补图" : "查看分镜",
      tab: unready || missing ? "全书资产" : "分镜",
    };
  }

  const next = bundle.chapters.find((c) => c.index > chapter.index && c.status !== "storyboarded");
  if (next) {
    return {
      step: "next_chapter",
      index: 5,
      title: "下一章",
      tip: `「${chapter.title}」已完成。可继续「${next.title}」分镜。`,
      cta: `进入 ${next.title}`,
      tab: "原文",
    };
  }

  return {
    step: "export",
    index: 5,
    title: "导出策划包",
    tip: "全书资产与分镜就绪，导出 JSON / Markdown。",
    cta: "导出 JSON",
  };
}

export function stepProgressIndex(step: FlowStepId): number {
  const map: Record<FlowStepId, number> = {
    style: 0,
    generate_assets: 1,
    upload: 2,
    storyboard: 3,
    review: 4,
    export: 5,
    next_chapter: 5,
  };
  return map[step] ?? 0;
}

export function statusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "待分镜";
    case "proposals":
      return "待分镜";
    case "assets_confirmed":
      return "可分镜";
    case "storyboarded":
      return "已分镜";
    default:
      return status;
  }
}
