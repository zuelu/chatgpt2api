"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Eraser, Lasso, Redo2, Undo2 } from "lucide-react";

import { cn } from "@/lib/utils";

export type LassoPoint = { x: number; y: number };

type ImageEditCanvasProps = {
  /** 原图 dataURL */
  imageUrl: string;
  /** 已选区域变化时回调；无选区时回传 null */
  onMaskChange: (maskDataUrl: string | null) => void;
  /** 图片变更（切换原图）时用于重置选区 */
  imageKey?: string;
  className?: string;
  disabled?: boolean;
};

const MIN_POINT_DISTANCE = 0.004;
const MIN_PATH_POINTS = 3;

/**
 * 局部编辑画布：用套索圈出要修改的区域。
 *
 * 交互参照 ChatGPT 网页版：选中的区域保持原样高亮，未选中的区域压暗。
 * 导出的 mask 中，圈选区域为透明（alpha=0），其余为不透明，
 * 与后端 `_composite_mask()` 的约定一致（透明=需要编辑，不透明=保留）。
 */
export function ImageEditCanvas({
  imageUrl,
  onMaskChange,
  imageKey,
  className,
  disabled = false,
}: ImageEditCanvasProps) {
  const imageRef = useRef<HTMLImageElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const drawingRef = useRef<LassoPoint[] | null>(null);

  const [paths, setPaths] = useState<LassoPoint[][]>([]);
  const [redoStack, setRedoStack] = useState<LassoPoint[][]>([]);
  const [isDrawing, setIsDrawing] = useState(false);
  const [isImageReady, setIsImageReady] = useState(false);

  // 切换原图时清空选区
  useEffect(() => {
    setPaths([]);
    setRedoStack([]);
    drawingRef.current = null;
    setIsDrawing(false);
  }, [imageKey, imageUrl]);

  const tracePath = useCallback(
    (ctx: CanvasRenderingContext2D, path: LassoPoint[], width: number, height: number) => {
      if (path.length === 0) {
        return;
      }
      ctx.beginPath();
      path.forEach((point, index) => {
        const x = point.x * width;
        const y = point.y * height;
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.closePath();
    },
    [],
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
    const targetWidth = Math.max(1, Math.round(rect.width * dpr));
    const targetHeight = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
      canvas.width = targetWidth;
      canvas.height = targetHeight;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const active = drawingRef.current;
    const allPaths = active && active.length > 1 ? [...paths, active] : paths;
    if (allPaths.length === 0) {
      return;
    }

    // 未选中的区域压暗
    ctx.fillStyle = "rgba(15, 23, 42, 0.52)";
    ctx.fillRect(0, 0, rect.width, rect.height);

    // 圈选区域挖空，露出原图
    ctx.globalCompositeOperation = "destination-out";
    ctx.fillStyle = "#000";
    for (const path of allPaths) {
      tracePath(ctx, path, rect.width, rect.height);
      ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";

    // 选区描边
    ctx.strokeStyle = "rgba(255, 255, 255, 0.95)";
    ctx.lineWidth = 2;
    ctx.setLineDash([7, 5]);
    for (const path of allPaths) {
      tracePath(ctx, path, rect.width, rect.height);
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }, [paths, tracePath]);

  useEffect(() => {
    paint();
  }, [paint, isImageReady]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(() => {
      paint();
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
    };
  }, [paint]);

  const buildMaskDataUrl = useCallback(
    (source: LassoPoint[][]): string | null => {
      const image = imageRef.current;
      const width = image?.naturalWidth || 0;
      const height = image?.naturalHeight || 0;
      const usable = source.filter((path) => path.length >= MIN_PATH_POINTS);
      if (width <= 0 || height <= 0 || usable.length === 0) {
        return null;
      }
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        return null;
      }
      // 默认全部不透明 = 全部保留
      ctx.fillStyle = "#000000";
      ctx.fillRect(0, 0, width, height);
      // 圈选处挖成透明 = 需要修改
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = "#000000";
      for (const path of usable) {
        tracePath(ctx, path, width, height);
        ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";
      return canvas.toDataURL("image/png");
    },
    [tracePath],
  );

  const commitPaths = useCallback(
    (next: LassoPoint[][]) => {
      setPaths(next);
      onMaskChange(buildMaskDataUrl(next));
    },
    [buildMaskDataUrl, onMaskChange],
  );

  const pointFromEvent = useCallback((event: React.PointerEvent<HTMLCanvasElement>): LassoPoint => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(1, rect.width))),
      y: Math.min(1, Math.max(0, (event.clientY - rect.top) / Math.max(1, rect.height))),
    };
  }, []);

  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (disabled) {
      return;
    }
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drawingRef.current = [pointFromEvent(event)];
    setIsDrawing(true);
    paint();
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const active = drawingRef.current;
    if (!active || disabled) {
      return;
    }
    event.preventDefault();
    const point = pointFromEvent(event);
    const last = active[active.length - 1];
    if (last) {
      const dx = point.x - last.x;
      const dy = point.y - last.y;
      if (Math.hypot(dx, dy) < MIN_POINT_DISTANCE) {
        return;
      }
    }
    active.push(point);
    paint();
  };

  const finishStroke = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const active = drawingRef.current;
    drawingRef.current = null;
    setIsDrawing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (!active || active.length < MIN_PATH_POINTS) {
      paint();
      return;
    }
    setRedoStack([]);
    commitPaths([...paths, active]);
  };

  const handleUndo = () => {
    if (paths.length === 0) {
      return;
    }
    const next = paths.slice(0, -1);
    setRedoStack((prev) => [...prev, paths[paths.length - 1]]);
    commitPaths(next);
  };

  const handleRedo = () => {
    if (redoStack.length === 0) {
      return;
    }
    const restored = redoStack[redoStack.length - 1];
    setRedoStack((prev) => prev.slice(0, -1));
    commitPaths([...paths, restored]);
  };

  const handleClear = () => {
    if (paths.length === 0) {
      return;
    }
    setRedoStack([]);
    commitPaths([]);
  };

  const hasSelection = paths.length > 0;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div
        ref={containerRef}
        className="relative overflow-hidden rounded-2xl border border-stone-200 bg-stone-100 dark:border-white/10 dark:bg-stone-900"
      >
        <img
          ref={imageRef}
          src={imageUrl}
          alt="待编辑的图片"
          draggable={false}
          onLoad={() => {
            setIsImageReady(true);
            paint();
          }}
          className="block w-full select-none"
        />
        <canvas
          ref={overlayRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={finishStroke}
          onPointerCancel={finishStroke}
          className={cn(
            "absolute inset-0 size-full touch-none",
            disabled ? "cursor-not-allowed" : isDrawing ? "cursor-crosshair" : "cursor-crosshair",
          )}
        />
        {!hasSelection && !isDrawing ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center p-3">
            <span className="rounded-full bg-stone-950/75 px-3 py-1.5 text-xs font-medium text-white backdrop-blur">
              按住并拖动，圈出要修改的区域
            </span>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-stone-100 px-3 py-1.5 text-xs font-medium text-stone-700 dark:bg-white/10 dark:text-stone-200">
          <Lasso className="size-3.5" />
          套索
        </span>
        <button
          type="button"
          onClick={handleUndo}
          disabled={paths.length === 0}
          className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:border-stone-300 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-white/10 dark:bg-stone-900 dark:text-stone-200"
        >
          <Undo2 className="size-3.5" />
          撤销
        </button>
        <button
          type="button"
          onClick={handleRedo}
          disabled={redoStack.length === 0}
          className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:border-stone-300 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-white/10 dark:bg-stone-900 dark:text-stone-200"
        >
          <Redo2 className="size-3.5" />
          重做
        </button>
        <button
          type="button"
          onClick={handleClear}
          disabled={paths.length === 0}
          className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:border-stone-300 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-white/10 dark:bg-stone-900 dark:text-stone-200"
        >
          <Eraser className="size-3.5" />
          清除选区
        </button>
        <span className="text-xs text-stone-500 dark:text-stone-400">
          {hasSelection ? `已圈出 ${paths.length} 个区域，只改这些地方` : "不圈选则整张图都可以改"}
        </span>
      </div>
    </div>
  );
}

export default ImageEditCanvas;
