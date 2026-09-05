import type { Asset, Bundle, Chapter, Shot } from "./api";
import { normalizeKind } from "./api";

export type TabName = "原文" | "资产" | "分镜";

export type FlowStepId =
  | "style"
  | "extract"
  | "confirm"
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
  { id: "extract", label: "抽资产" },
  { id: "confirm", label: "确认" },
  { id: "upload", label: "上传图" },
  { id: "storyboard", label: "分镜" },
  { id: "review", label: "校对" },
  { id: "export", label: "导出" },
] as const;

export function pipelineSteps() {
  return PIPELINE;
}

function chapterAssets(bundle: Bundle, chapter: Chapter): Asset[] {
  return bundle.assets.filter(
    (a) => !a.created_chapter_id || a.created_chapter_id === chapter.id || a.confirmed,
  );
}

function missingRefCount(assets: Asset[]): number {
  let n = 0;
  for (const a of assets) {
    if (normalizeKind(a.kind) === "character") {
      if (!a.half_path || !a.full_path) n += 1;
    } else if (!a.image_path) {
      n += 1;
    }
  }
  return n;
}

export function deriveGuide(bundle: Bundle, chapter: Chapter | undefined, shots: Shot[]): FlowGuide {
  const styleOk = Boolean((bundle.project.style || "").trim());
  if (!styleOk) {
    return {
      step: "style",
      index: 0,
      title: "第 1 步 · 填写项目画风",
      tip: "画风会注入所有资产描述和首帧提示词。未填写时，分镜无法标记为「首帧就绪」。",
      cta: "保存画风设置",
    };
  }

  if (!chapter) {
    return {
      step: "extract",
      index: 1,
      title: "选择章节",
      tip: "左侧选择要处理的章节，然后按步骤推进。",
      cta: "选择章节",
      tab: "原文",
    };
  }

  const status = chapter.status;
  const assets = chapterAssets(bundle, chapter);
  const missing = missingRefCount(assets.filter((a) => a.confirmed));
  const hasProposals = bundle.proposals.some((p) => p.chapter_id === chapter.id);

  if (status === "pending" || (status === "proposals" && !hasProposals && assets.length === 0)) {
    return {
      step: "extract",
      index: 1,
      title: "第 2 步 · 抽取本章资产",
      tip: `阅读「${chapter.title}」，让模型提出人物 / 场景 / 物品提案。不会立刻写入，需你确认。`,
      cta: "抽取本章资产",
      tab: "原文",
    };
  }

  if (status === "proposals" || hasProposals) {
    return {
      step: "confirm",
      index: 2,
      title: "第 3 步 · 确认资产提案",
      tip: "勾选要保留的提案：新建、合并昵称、复制变体或补充特征。确认后才进入分镜。",
      cta: "去确认资产",
      tab: "资产",
    };
  }

  if (status === "assets_confirmed") {
    if (missing > 0) {
      return {
        step: "upload",
        index: 3,
        title: "第 4 步 · 上传参考图（建议）",
        tip: `还有 ${missing} 个资产缺图。角色需半身+全身，场景/物品各一张。可先生成分镜脚本，缺图镜会标「首帧未就绪」。`,
        cta: "去上传参考图",
        tab: "资产",
      };
    }
    return {
      step: "storyboard",
      index: 4,
      title: "第 5 步 · 生成本章分镜",
      tip: "根据已确认资产切镜：站位、朝向、首帧双提示词与 H3 视频脚本。",
      cta: "生成本章分镜",
      tab: "原文",
    };
  }

  if (status === "storyboarded") {
    const unready = shots.filter((s) => s.first_frame_unready).length;
    if (unready > 0 || missing > 0) {
      return {
        step: "review",
        index: 5,
        title: "第 6 步 · 补图与校对分镜",
        tip: unready
          ? `有 ${unready} 个分镜首帧未就绪：补传参考图或改提示词后可「按站位重编译」。`
          : "检查运镜、旁白与位置化台词；确认无角色名泄漏到 H3 句。",
        cta: unready || missing ? "去资产补图" : "查看分镜",
        tab: unready || missing ? "资产" : "分镜",
      };
    }

    const chapters = [...bundle.chapters].sort((a, b) => a.index - b.index);
    const next = chapters.find((c) => c.index > chapter.index && c.status !== "storyboarded");
    if (next) {
      return {
        step: "next_chapter",
        index: 6,
        title: "本章已完成 · 进入下一章",
        tip: `「${chapter.title}」已出分镜。下一章「${next.title}」尚未完成，继续逐章推进。`,
        cta: `处理 ${next.title}`,
        tab: "原文",
      };
    }

    return {
      step: "export",
      index: 6,
      title: "第 7 步 · 导出策划包",
      tip: "导出 novel2lens.json + shots.md，供后续 Qwen 首帧与 H3 视频使用。",
      cta: "导出 JSON",
    };
  }

  return {
    step: "extract",
    index: 1,
    title: "继续本章流程",
    tip: "按左侧章节状态推进：抽取 → 确认 → 上传图 → 分镜 → 导出。",
    cta: "抽取本章资产",
    tab: "原文",
  };
}

export function stepProgressIndex(guide: FlowGuide): number {
  const map: Record<FlowStepId, number> = {
    style: 0,
    extract: 1,
    confirm: 2,
    upload: 3,
    storyboard: 4,
    review: 5,
    export: 6,
    next_chapter: 6,
  };
  return map[guide.step];
}

export function statusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "待抽取";
    case "proposals":
      return "待确认";
    case "assets_confirmed":
      return "待分镜";
    case "storyboarded":
      return "已分镜";
    default:
      return status;
  }
}
