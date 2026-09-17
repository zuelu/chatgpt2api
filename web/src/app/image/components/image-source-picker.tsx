"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ImageOff, LoaderCircle, Upload } from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fetchManagedImages, type ManagedImage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ImageConversation } from "@/store/image-conversations";

export type PickedImage = {
  name: string;
  type: string;
  dataUrl: string;
};

type ImageSourcePickerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  conversations: ImageConversation[];
  onPick: (image: PickedImage) => void;
  onPickFromDevice: () => void;
};

const HISTORY_LIMIT = 30;
const GALLERY_LIMIT = 60;

// b64 转 blob URL，避免超长 data URL 直接进 DOM
const blobUrlCache = new Map<string, string>();

function b64ToBlobUrl(b64: string) {
  const cached = blobUrlCache.get(b64);
  if (cached) {
    return cached;
  }
  try {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    const url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
    blobUrlCache.set(b64, url);
    return url;
  } catch {
    return "";
  }
}

async function remoteUrlToDataUrl(url: string, t: TFunction): Promise<string> {
  const absolute = url.startsWith("http") ? url : `${window.location.origin}${url}`;
  const response = await fetch(absolute);
  if (!response.ok) {
    throw new Error(t("sourcePicker.errors.loadFailed", { status: response.status }));
  }
  const blob = await response.blob();
  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error(t("sourcePicker.errors.readFailed")));
    reader.readAsDataURL(blob);
  });
}

function fileNameFromUrl(url: string, fallback: string) {
  try {
    const path = new URL(url, window.location.origin).pathname;
    const name = path.split("/").pop();
    return name && name.includes(".") ? name : fallback;
  } catch {
    return fallback;
  }
}

export function ImageSourcePicker({
  open,
  onOpenChange,
  conversations,
  onPick,
  onPickFromDevice,
}: ImageSourcePickerProps) {
  const { t } = useTranslation("image");
  const [tab, setTab] = useState("history");
  const [gallery, setGallery] = useState<ManagedImage[]>([]);
  const [isLoadingGallery, setIsLoadingGallery] = useState(false);
  const [galleryError, setGalleryError] = useState("");
  const [loadingKey, setLoadingKey] = useState("");

  const historyItems = useMemo(() => {
    const collected: Array<{ key: string; b64?: string; url?: string; createdAt: string }> = [];
    for (const conversation of conversations) {
      for (const turn of conversation.turns) {
        if (turn.resultsDeleted) {
          continue;
        }
        for (const image of turn.images) {
          if (image.status !== "success") {
            continue;
          }
          if (image.b64_json) {
            collected.push({
              key: image.id,
              b64: image.b64_json,
              createdAt: turn.createdAt,
            });
          } else if (image.url) {
            collected.push({
              key: image.id,
              url: image.url,
              createdAt: turn.createdAt,
            });
          }
        }
      }
    }
    return collected
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .slice(0, HISTORY_LIMIT)
      .map((item) => ({
        ...item,
        src: item.b64 ? b64ToBlobUrl(item.b64) : item.url || "",
      }))
      .filter((item) => Boolean(item.src));
  }, [conversations]);

  const loadGallery = useCallback(async () => {
    setIsLoadingGallery(true);
    setGalleryError("");
    try {
      const result = await fetchManagedImages({});
      setGallery(result.items.slice(0, GALLERY_LIMIT));
    } catch (error) {
      setGalleryError(error instanceof Error ? error.message : t("sourcePicker.errors.galleryFailed"));
    } finally {
      setIsLoadingGallery(false);
    }
  }, [t]);

  useEffect(() => {
    if (open && tab === "gallery" && gallery.length === 0 && !isLoadingGallery && !galleryError) {
      void loadGallery();
    }
  }, [open, tab, gallery.length, isLoadingGallery, galleryError, loadGallery]);

  const pickHistoryItem = async (item: { b64?: string; url?: string; key: string }) => {
    setLoadingKey(item.key);
    try {
      const dataUrl = item.b64
        ? `data:image/png;base64,${item.b64}`
        : await remoteUrlToDataUrl(item.url || "", t);
      onPick({ name: `history-${item.key}.png`, type: "image/png", dataUrl });
      onOpenChange(false);
    } catch (error) {
      setGalleryError(error instanceof Error ? error.message : t("sourcePicker.errors.readFailed"));
    } finally {
      setLoadingKey("");
    }
  };

  const pickGalleryItem = async (item: ManagedImage) => {
    const key = `gallery-${item.rel}`;
    setLoadingKey(key);
    try {
      const dataUrl = await remoteUrlToDataUrl(item.url, t);
      onPick({ name: item.name || fileNameFromUrl(item.url, "gallery.png"), type: "image/png", dataUrl });
      onOpenChange(false);
    } catch (error) {
      setGalleryError(error instanceof Error ? error.message : t("sourcePicker.errors.readFailed"));
    } finally {
      setLoadingKey("");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[min(80dvh,720px)] w-[94vw] max-w-[720px] flex-col overflow-hidden rounded-[28px] p-0">
        <DialogHeader className="px-6 pt-6 pb-3">
          <DialogTitle className="text-lg font-bold tracking-tight">{t("sourcePicker.title")}</DialogTitle>
        </DialogHeader>

        <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col gap-0">
          <div className="flex items-center justify-between gap-3 px-6 pb-3">
            <TabsList className="rounded-full bg-stone-100 p-1">
              <TabsTrigger
                value="history"
                className="rounded-full px-4 py-1.5 text-xs font-medium data-[state=active]:bg-white data-[state=active]:shadow-sm"
              >
                {t("sourcePicker.tabs.history")}
              </TabsTrigger>
              <TabsTrigger
                value="gallery"
                className="rounded-full px-4 py-1.5 text-xs font-medium data-[state=active]:bg-white data-[state=active]:shadow-sm"
              >
                {t("sourcePicker.tabs.gallery")}
              </TabsTrigger>
            </TabsList>
            <button
              type="button"
              onClick={() => {
                onOpenChange(false);
                onPickFromDevice();
              }}
              className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:border-stone-300 hover:bg-stone-50 dark:border-white/10 dark:bg-stone-900 dark:text-stone-200"
            >
              <Upload className="size-3.5" />
              {t("sourcePicker.upload")}
            </button>
          </div>

          {galleryError ? (
            <div className="mx-6 mb-2 flex items-center justify-between gap-3 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">
              <span>{galleryError}</span>
              {tab === "gallery" ? (
                <button type="button" className="shrink-0 font-medium underline" onClick={() => void loadGallery()}>
                  {t("sourcePicker.retry")}
                </button>
              ) : null}
            </div>
          ) : null}

          <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
            <TabsContent value="history" className="mt-0">
              {historyItems.length === 0 ? (
                <EmptyHint text={t("sourcePicker.emptyHistory")} />
              ) : (
                <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
                  {historyItems.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      disabled={Boolean(loadingKey)}
                      onClick={() => void pickHistoryItem(item)}
                      aria-label={t("sourcePicker.selectHistory", { name: item.key })}
                      className={cn(
                        "group relative aspect-square overflow-hidden rounded-2xl border border-stone-200 bg-stone-50 transition hover:border-stone-400",
                        loadingKey === item.key && "opacity-60",
                      )}
                    >
                      <img src={item.src} alt={t("sourcePicker.historyAlt", { name: item.key })} className="size-full object-cover" />
                      {loadingKey === item.key ? (
                        <span className="absolute inset-0 flex items-center justify-center bg-white/70">
                          <LoaderCircle className="size-4 animate-spin text-stone-600" />
                        </span>
                      ) : null}
                    </button>
                  ))}
                </div>
              )}
            </TabsContent>

            <TabsContent value="gallery" className="mt-0">
              {isLoadingGallery ? (
                <div className="flex items-center justify-center py-16">
                  <LoaderCircle className="size-5 animate-spin text-stone-400" />
                </div>
              ) : gallery.length === 0 ? (
                <EmptyHint text={t("sourcePicker.emptyGallery")} />
              ) : (
                <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
                  {gallery.map((item) => {
                    const key = `gallery-${item.rel}`;
                    return (
                      <button
                        key={key}
                        type="button"
                        disabled={Boolean(loadingKey)}
                        onClick={() => void pickGalleryItem(item)}
                        aria-label={t("sourcePicker.selectGallery", { name: item.name || item.rel })}
                        className={cn(
                          "group relative aspect-square overflow-hidden rounded-2xl border border-stone-200 bg-stone-50 transition hover:border-stone-400",
                          loadingKey === key && "opacity-60",
                        )}
                      >
                        <img
                          src={item.thumbnail_url || item.url}
                          alt={item.name || t("sourcePicker.galleryAlt")}
                          loading="lazy"
                          className="size-full object-cover"
                        />
                        {loadingKey === key ? (
                          <span className="absolute inset-0 flex items-center justify-center bg-white/70">
                            <LoaderCircle className="size-4 animate-spin text-stone-600" />
                          </span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              )}
            </TabsContent>
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <ImageOff className="size-8 text-stone-300" />
      <p className="max-w-xs text-sm text-stone-500">{text}</p>
    </div>
  );
}

export default ImageSourcePicker;
