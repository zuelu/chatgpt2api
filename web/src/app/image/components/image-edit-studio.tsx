"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Eraser, MessageSquarePlus, Redo2, Send, Undo2, X } from "lucide-react";

import { cn } from "@/lib/utils";

export type StudioPoint = { x: number; y: number };

export type StudioAnnotation = {
  id: string;
  x: number;
  y: number;
  text: string;
};

export type StudioTool = "comment" | "erase" | "lasso";

export type StudioSelection = {
  maskDataUrl: string | null;
  annotations: StudioAnnotation[];
  /** 把标注钉画进原图后的版本，提交时作为参考图发给上游 */
  annotatedDataUrl?: string | null;
};

type ImageEditStudioProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  imageUrl: string;
  title?: string;
  prompt: string;
  onPromptChange: (value: string) => void;
  model: string;
  onModelChange?: (value: string) => void;
  modelOptions?: string[];
  size: string;
  quality: string;
  busy?: boolean;
  initialSelection?: StudioSelection;
  onSelectionChange: (selection: StudioSelection) => void;
  onSubmit: () => void | Promise<void>;
};

const MIN_PATH_POINTS = 3;
const MIN_POINT_DISTANCE = 0.004;
/** 擦除笔刷直径 = 图片最短边的百分比。1254px 的图，1% ≈ 12px，5% ≈ 63px。 */
const BRUSH_MIN = 1;
const BRUSH_MAX = 20;
const BRUSH_DEFAULT = 5;

const TOOLS: Array<{ id: StudioTool; label: string; hint: string }> = [
  { id: "comment", label: "标注", hint: "点击图片添加标注" },
  { id: "erase", label: "擦除", hint: "涂抹你想去掉的区域" },
  { id: "lasso", label: "套索", hint: "圈出你要修改的区域" },
];

function newId() {
  return `an_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

/**
 * 全屏图片编辑器，交互对齐 ChatGPT 网页版：
 * 顶部工具胶囊 + 工具激活后变提示条、左侧竖向笔刷滑块、底部「描述修改」输入条。
 * 导出 mask 时，涂抹/圈选区域为透明（需要修改），其余不透明（保留）。
 */
export function ImageEditStudio({
  open,
  onOpenChange,
  imageUrl,
  title,
  prompt,
  onPromptChange,
  model,
  modelOptions = [],
  onModelChange,
  size,
  quality,
  busy = false,
  initialSelection,
  onSelectionChange,
  onSubmit,
}: ImageEditStudioProps) {
  const imageRef = useRef<HTMLImageElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const drawingRef = useRef<StudioPoint[] | null>(null);
  /** 鼠标在画布上的位置，用来实时画出笔刷光标 */
  const hoverRef = useRef<StudioPoint | null>(null);

  const [activeTool, setActiveTool] = useState<StudioTool | null>(null);
  const [brushSize, setBrushSize] = useState(BRUSH_DEFAULT);
  const [lassoPaths, setLassoPaths] = useState<StudioPoint[][]>([]);
  const [brushStrokes, setBrushStrokes] = useState<StudioPoint[][]>([]);
  const [annotations, setAnnotations] = useState<StudioAnnotation[]>([]);
  const [redoStack, setRedoStack] = useState<{ lasso: StudioPoint[][]; brush: StudioPoint[][] }[]>([]);
  const [draftAnnotation, setDraftAnnotation] = useState<StudioPoint | null>(null);
  const [draftText, setDraftText] = useState("");
  const [isDrawing, setIsDrawing] = useState(false);

  // 打开时同步外部传入的选区
  useEffect(() => {
    if (!open) {
      return;
    }
    setLassoPaths([]);
    setBrushStrokes([]);
    setRedoStack([]);
    setAnnotations(initialSelection?.annotations ?? []);
    setDraftAnnotation(null);
    setDraftText("");
    setActiveTool(null);
    hoverRef.current = null;
    // 只在打开瞬间同步一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, imageUrl]);

  const buildMaskDataUrl = useCallback(
    (lasso: StudioPoint[][], brush: StudioPoint[][]): string | null => {
      const image = imageRef.current;
      const width = image?.naturalWidth || 0;
      const height = image?.naturalHeight || 0;
      const usableLasso = lasso.filter((p) => p.length >= MIN_PATH_POINTS);
      const usableBrush = brush.filter((p) => p.length > 0);
      if (width <= 0 || height <= 0 || (usableLasso.length === 0 && usableBrush.length === 0)) {
        return null;
      }
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        return null;
      }
      ctx.fillStyle = "#000000";
      ctx.fillRect(0, 0, width, height);
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = "#000000";
      for (const path of usableLasso) {
        ctx.beginPath();
        path.forEach((point, index) => {
          const x = point.x * width;
          const y = point.y * height;
          index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.fill();
      }
      const shortest = Math.min(width, height);
      for (const stroke of usableBrush) {
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.lineWidth = (brushSize / 100) * shortest;
        ctx.beginPath();
        stroke.forEach((point, index) => {
          const x = point.x * width;
          const y = point.y * height;
          index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        if (stroke.length === 1) {
          const only = stroke[0];
          ctx.arc(only.x * width, only.y * height, ctx.lineWidth / 2, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.stroke();
        }
      }
      ctx.globalCompositeOperation = "source-over";
      return canvas.toDataURL("image/png");
    },
    [brushSize],
  );

  const paint = useCallback(() => {
    const canvas = overlayRef.current;
    const image = imageRef.current;
    if (!canvas || !image) {
      return;
    }
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const live = drawingRef.current;
    const liveLasso = activeTool === "lasso" && live && live.length > 1 ? [live] : [];
    const liveBrush = activeTool === "erase" && live && live.length > 0 ? [live] : [];
    const allLasso = [...lassoPaths, ...liveLasso];
    const allBrush = [...brushStrokes, ...liveBrush];
    const hasSelection = allLasso.length > 0 || allBrush.length > 0;

    if (hasSelection) {
      // 未选中的区域压暗
      ctx.fillStyle = "rgba(15, 23, 42, 0.5)";
      ctx.fillRect(0, 0, rect.width, rect.height);
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = "#000";
      for (const path of allLasso) {
        ctx.beginPath();
        path.forEach((p, i) => {
          const x = p.x * rect.width;
          const y = p.y * rect.height;
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.fill();
      }
      const shortest = Math.min(rect.width, rect.height);
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#000";
      ctx.fillStyle = "#000";
      ctx.lineWidth = (brushSize / 100) * shortest;
      for (const stroke of allBrush) {
        ctx.beginPath();
        stroke.forEach((p, i) => {
          const x = p.x * rect.width;
          const y = p.y * rect.height;
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        if (stroke.length === 1) {
          ctx.arc(stroke[0].x * rect.width, stroke[0].y * rect.height, ctx.lineWidth / 2, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.stroke();
        }
      }
      ctx.globalCompositeOperation = "source-over";
      // 描边
      ctx.strokeStyle = "rgba(255,255,255,0.95)";
      ctx.lineWidth = 2;
      ctx.setLineDash([7, 5]);
      for (const path of allLasso) {
        ctx.beginPath();
        path.forEach((p, i) => {
          const x = p.x * rect.width;
          const y = p.y * rect.height;
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    // 擦除时跟随鼠标画出真实笔刷大小，避免"看不见笔刷多大"
    const hover = hoverRef.current;
    if (activeTool === "erase" && hover) {
      const radius = Math.max(1, ((brushSize / 100) * Math.min(rect.width, rect.height)) / 2);
      const cx = hover.x * rect.width;
      const cy = hover.y * rect.height;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(15, 23, 42, 0.28)";
      ctx.fill();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.95)";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.strokeStyle = "rgba(15, 23, 42, 0.55)";
      ctx.lineWidth = 0.75;
      ctx.stroke();
    }
  }, [activeTool, lassoPaths, brushStrokes, brushSize]);

  useEffect(() => {
    paint();
  }, [paint]);

  useEffect(() => {
    const el = stageRef.current;
    if (!el || typeof ResizeObserver === "undefined") {
      return;
    }
    const ro = new ResizeObserver(() => paint());
    ro.observe(el);
    return () => ro.disconnect();
  }, [paint]);

  /** 把标注钉子画进原图，让上游能看到「第几号标注在哪个位置」 */
  const buildAnnotatedDataUrl = useCallback(
    (items: StudioAnnotation[]): string | null => {
      const image = imageRef.current;
      const width = image?.naturalWidth || 0;
      const height = image?.naturalHeight || 0;
      if (!image || width <= 0 || height <= 0 || items.length === 0) {
        return null;
      }
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        return null;
      }
      try {
        ctx.drawImage(image, 0, 0, width, height);
      } catch {
        return null;
      }
      const radius = Math.max(14, Math.min(width, height) * 0.022);
      ctx.font = `bold ${Math.round(radius * 1.15)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      items.forEach((item, index) => {
        const x = item.x * width;
        const y = item.y * height;
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = "#2563eb";
        ctx.fill();
        ctx.lineWidth = Math.max(2, radius * 0.18);
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();
        ctx.fillStyle = "#ffffff";
        ctx.fillText(String(index + 1), x, y + 1);
      });
      try {
        return canvas.toDataURL("image/png");
      } catch {
        return null;
      }
    },
    [],
  );

  const emit = useCallback(
    (nextLasso: StudioPoint[][], nextBrush: StudioPoint[][], nextAnnotations: StudioAnnotation[]) => {
      onSelectionChange({
        maskDataUrl: buildMaskDataUrl(nextLasso, nextBrush),
        annotations: nextAnnotations,
        annotatedDataUrl: buildAnnotatedDataUrl(nextAnnotations),
      });
    },
    [buildMaskDataUrl, buildAnnotatedDataUrl, onSelectionChange],
  );

  const pointFromEvent = (event: React.PointerEvent<HTMLCanvasElement>): StudioPoint => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(1, rect.width))),
      y: Math.min(1, Math.max(0, (event.clientY - rect.top) / Math.max(1, rect.height))),
    };
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!imageUrl || busy) {
      return;
    }
    event.preventDefault();
    if (activeTool === "comment") {
      setDraftAnnotation(pointFromEvent(event));
      setDraftText("");
      return;
    }
    if (activeTool !== "erase" && activeTool !== "lasso") {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    drawingRef.current = [pointFromEvent(event)];
    setIsDrawing(true);
    paint();
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const point = pointFromEvent(event);
    if (activeTool === "erase") {
      hoverRef.current = point;
    }
    const live = drawingRef.current;
    if (!live || busy) {
      // 没在画的时候也要重绘，才能看到笔刷光标
      if (activeTool === "erase") {
        paint();
      }
      return;
    }
    event.preventDefault();
    const last = live[live.length - 1];
    if (last && Math.hypot(point.x - last.x, point.y - last.y) < MIN_POINT_DISTANCE) {
      return;
    }
    live.push(point);
    paint();
  };

  const handlePointerLeave = () => {
    if (activeTool !== "erase" || drawingRef.current) {
      return;
    }
    hoverRef.current = null;
    paint();
  };

  const finishStroke = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const live = drawingRef.current;
    drawingRef.current = null;
    setIsDrawing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (!live) {
      return;
    }
    if (activeTool === "lasso") {
      if (live.length < MIN_PATH_POINTS) {
        paint();
        return;
      }
      const next = [...lassoPaths, live];
      setLassoPaths(next);
      setRedoStack([]);
      emit(next, brushStrokes, annotations);
      return;
    }
    if (activeTool === "erase") {
      if (live.length === 0) {
        paint();
        return;
      }
      const next = [...brushStrokes, live];
      setBrushStrokes(next);
      setRedoStack([]);
      emit(lassoPaths, next, annotations);
    }
  };

  const handleUndo = () => {
    if (brushStrokes.length > 0) {
      const next = brushStrokes.slice(0, -1);
      setRedoStack((prev) => [...prev, { lasso: lassoPaths, brush: brushStrokes }]);
      setBrushStrokes(next);
      emit(lassoPaths, next, annotations);
      return;
    }
    if (lassoPaths.length > 0) {
      const next = lassoPaths.slice(0, -1);
      setRedoStack((prev) => [...prev, { lasso: lassoPaths, brush: brushStrokes }]);
      setLassoPaths(next);
      emit(next, brushStrokes, annotations);
    }
  };

  const handleRedo = () => {
    const last = redoStack[redoStack.length - 1];
    if (!last) {
      return;
    }
    setRedoStack((prev) => prev.slice(0, -1));
    setLassoPaths(last.lasso);
    setBrushStrokes(last.brush);
    emit(last.lasso, last.brush, annotations);
  };

  const handleClear = () => {
    setRedoStack([]);
    setLassoPaths([]);
    setBrushStrokes([]);
    setDraftAnnotation(null);
    setAnnotations([]);
    onSelectionChange({ maskDataUrl: null, annotations: [] });
  };

  const commitAnnotation = () => {
    if (!draftAnnotation || !draftText.trim()) {
      setDraftAnnotation(null);
      setDraftText("");
      return;
    }
    const next = [
      ...annotations,
      { id: newId(), x: draftAnnotation.x, y: draftAnnotation.y, text: draftText.trim() },
    ];
    setAnnotations(next);
    setDraftAnnotation(null);
    setDraftText("");
    emit(lassoPaths, brushStrokes, next);
  };

  const removeAnnotation = (id: string) => {
    const next = annotations.filter((a) => a.id !== id);
    setAnnotations(next);
    emit(lassoPaths, brushStrokes, next);
  };

  const hasSelection = lassoPaths.length > 0 || brushStrokes.length > 0;
  const canSubmit = Boolean(prompt.trim()) && !busy;
  const activeHint = useMemo(() => TOOLS.find((t) => t.id === activeTool)?.hint ?? "", [activeTool]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[100] flex flex-col bg-white dark:bg-stone-950">
      {/* 顶栏 */}
      <header className="relative flex shrink-0 items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="inline-flex size-9 items-center justify-center rounded-full text-stone-600 transition hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-white/10"
          aria-label="关闭编辑器"
        >
          <X className="size-5" />
        </button>
        <h2 className="truncate text-sm font-medium text-stone-800 dark:text-stone-100">
          {title || "编辑图片"}
        </h2>
        <div className="ml-auto flex items-center gap-2 text-xs text-stone-500 dark:text-stone-400">
          <span className="rounded-full bg-stone-100 px-2.5 py-1 dark:bg-white/10">{model}</span>
          <span className="rounded-full bg-stone-100 px-2.5 py-1 dark:bg-white/10">
            {size} · {quality}
          </span>
        </div>
      </header>

      {/* 工具条 / 提示条 */}
      <div className="pointer-events-none absolute inset-x-0 top-14 z-20 flex justify-center px-4">
        <div className="pointer-events-auto flex items-center gap-1 rounded-full border border-stone-200/80 bg-white/95 p-1 shadow-[0_18px_50px_-24px_rgba(15,23,42,0.45)] backdrop-blur dark:border-white/10 dark:bg-stone-900/95">
          {activeTool ? (
            <>
              <span className="px-3 text-xs font-medium text-stone-700 dark:text-stone-200 sm:text-[13px]">
                {activeHint}
              </span>
              {activeTool === "erase" ? (
                <>
                  <span className="h-5 w-px bg-stone-200 dark:bg-white/10" />
                  <span className="hidden text-[11px] text-stone-500 dark:text-stone-400 sm:inline">笔刷</span>
                  <input
                    type="range"
                    min={BRUSH_MIN}
                    max={BRUSH_MAX}
                    step={1}
                    value={brushSize}
                    onChange={(event) => setBrushSize(Number(event.target.value))}
                    aria-label="笔刷大小"
                    className="h-1.5 w-20 cursor-pointer appearance-none rounded-full bg-stone-200 accent-stone-900 dark:bg-white/20 dark:accent-white sm:w-32"
                  />
                  <span className="w-9 shrink-0 text-center text-[11px] tabular-nums text-stone-500 dark:text-stone-400">
                    {brushSize}%
                  </span>
                </>
              ) : null}
              <button
                type="button"
                disabled={!canSubmit}
                onClick={() => void onSubmit()}
                className="inline-flex items-center gap-1.5 rounded-full bg-stone-950 px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-300 dark:bg-white dark:text-stone-950 dark:disabled:bg-stone-700"
              >
                <Send className="size-3.5" />
                发送
              </button>
              <button
                type="button"
                onClick={() => setActiveTool(null)}
                className="inline-flex size-8 items-center justify-center rounded-full text-stone-500 transition hover:bg-stone-100 dark:hover:bg-white/10"
                aria-label="退出当前工具"
              >
                <X className="size-4" />
              </button>
            </>
          ) : (
            <>
              {TOOLS.map((tool) => (
                <button
                  key={tool.id}
                  type="button"
                  onClick={() => setActiveTool(tool.id)}
                  className="inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-medium text-stone-700 transition hover:bg-stone-100 dark:text-stone-200 dark:hover:bg-white/10 sm:text-[13px]"
                >
                  {tool.id === "comment" ? (
                    <MessageSquarePlus className="size-3.5" />
                  ) : tool.id === "erase" ? (
                    <Eraser className="size-3.5" />
                  ) : (
                    <Undo2 className="size-3.5" />
                  )}
                  {tool.label}
                </button>
              ))}
              <span className="mx-1 h-5 w-px bg-stone-200 dark:bg-white/10" />
              <button
                type="button"
                onClick={handleUndo}
                disabled={!hasSelection}
                className="inline-flex size-8 items-center justify-center rounded-full text-stone-600 transition hover:bg-stone-100 disabled:opacity-40 dark:text-stone-300 dark:hover:bg-white/10"
                aria-label="撤销"
              >
                <Undo2 className="size-4" />
              </button>
              <button
                type="button"
                onClick={handleRedo}
                disabled={redoStack.length === 0}
                className="inline-flex size-8 items-center justify-center rounded-full text-stone-600 transition hover:bg-stone-100 disabled:opacity-40 dark:text-stone-300 dark:hover:bg-white/10"
                aria-label="重做"
              >
                <Redo2 className="size-4" />
              </button>
              <button
                type="button"
                onClick={handleClear}
                disabled={!hasSelection && annotations.length === 0}
                className="inline-flex items-center rounded-full px-3 py-1.5 text-xs font-medium text-stone-600 transition hover:bg-stone-100 disabled:opacity-40 dark:text-stone-300 dark:hover:bg-white/10"
              >
                清除
              </button>
            </>
          )}
        </div>
      </div>

      {/* 画布 */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center px-4 pb-2">
        <div ref={stageRef} className="relative max-h-full max-w-full">
          <img
            ref={imageRef}
            src={imageUrl}
            alt="待编辑图片"
            draggable={false}
            onLoad={paint}
            className="block max-h-[calc(100dvh-15rem)] w-auto max-w-full select-none rounded-lg object-contain"
          />
          <canvas
            ref={overlayRef}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={finishStroke}
            onPointerCancel={finishStroke}
            onPointerLeave={handlePointerLeave}
            className={cn(
              "absolute inset-0 size-full touch-none",
              // 擦除时用自绘的笔刷光标替代系统光标
              activeTool === "erase" ? "cursor-none" : activeTool ? "cursor-crosshair" : "cursor-default",
            )}
          />

          {/* 标注钉 */}
          {annotations.map((annotation, index) => (
            <div
              key={annotation.id}
              className="absolute z-10 -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${annotation.x * 100}%`, top: `${annotation.y * 100}%` }}
            >
              <button
                type="button"
                onClick={() => removeAnnotation(annotation.id)}
                title={`${annotation.text}（点击删除）`}
                className="flex size-6 items-center justify-center rounded-full border-2 border-white bg-blue-600 text-[11px] font-bold text-white shadow-md"
              >
                {index + 1}
              </button>
            </div>
          ))}

          {/* 新标注输入 */}
          {draftAnnotation ? (
            <div
              className="absolute z-30 -translate-x-1/2 translate-y-3"
              style={{ left: `${draftAnnotation.x * 100}%`, top: `${draftAnnotation.y * 100}%` }}
            >
              <div className="flex items-center gap-1 rounded-2xl border border-stone-200 bg-white p-1.5 shadow-lg dark:border-white/10 dark:bg-stone-900">
                <input
                  autoFocus
                  value={draftText}
                  onChange={(event) => setDraftText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      commitAnnotation();
                    }
                    if (event.key === "Escape") {
                      setDraftAnnotation(null);
                      setDraftText("");
                    }
                  }}
                  placeholder="这里要改成什么？"
                  className="w-44 bg-transparent px-2 text-xs text-stone-800 outline-none placeholder:text-stone-400 dark:text-stone-100"
                />
                <button
                  type="button"
                  onClick={commitAnnotation}
                  className="rounded-full bg-stone-950 px-2.5 py-1 text-[11px] font-medium text-white dark:bg-white dark:text-stone-950"
                >
                  确定
                </button>
              </div>
            </div>
          ) : null}
        </div>

        {!activeTool ? (
          <div className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2">
            <span className="rounded-full bg-stone-950/75 px-3 py-1.5 text-xs font-medium text-white backdrop-blur">
              选一个工具标注或圈选，也可以直接描述修改
            </span>
          </div>
        ) : null}
      </div>

      {/* 底部输入条 */}
      <div className="flex shrink-0 justify-center px-4 pb-5">
        <div className="flex w-full max-w-[820px] items-center gap-2 rounded-[26px] border border-stone-200 bg-white px-3 py-2 shadow-[0_10px_40px_-28px_rgba(15,23,42,0.45)] dark:border-white/10 dark:bg-stone-900">
          {modelOptions.length > 0 ? (
            <select
              value={model}
              onChange={(event) => onModelChange?.(event.target.value)}
              className="shrink-0 rounded-full bg-stone-100 px-3 py-1.5 text-xs font-medium text-stone-700 outline-none dark:bg-white/10 dark:text-stone-200"
            >
              {modelOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          ) : null}
          <input
            value={prompt}
            onChange={(event) => onPromptChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (canSubmit) void onSubmit();
              }
            }}
            placeholder="描述修改"
            className="min-w-0 flex-1 bg-transparent px-2 py-1 text-sm text-stone-900 outline-none placeholder:text-stone-400 dark:text-stone-100"
          />
          {annotations.length > 0 ? (
            <span className="shrink-0 rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700">
              {annotations.length} 条标注
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => void onSubmit()}
            disabled={!canSubmit}
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-stone-950 text-white transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-300 dark:bg-white dark:text-stone-950 dark:disabled:bg-stone-700"
            aria-label="发送修改"
          >
            <Send className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

export default ImageEditStudio;
