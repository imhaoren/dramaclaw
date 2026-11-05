// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Sparkles, ChevronDown, BookOpen } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { queryKeys } from "@/lib/query-keys";
import { useStoryStructure, useAnalyzeStory } from "@/lib/queries/story";
import { useTaskStream } from "@/hooks/use-task-stream";
import { backendErrorToastMessage } from "@/lib/api-errors";

interface StoryStructureCardProps {
  project: string;
  /** 只有导入完成的项目才值得分析，未导入时不渲染。 */
  enabled: boolean;
}

/**
 * 全书结构分析卡片。
 *
 * 导入只保证原文落地；「这本书讲什么、能怎么分卷」要额外跑一次长任务
 * （几百章约几十次模型调用），所以按需触发而不是导入即跑。已有结果时
 * 直接展示；重跑会复用已摘要的章节，不会为同样的正文再付一次钱。
 *
 * 导入完成后会主动问一次（toast 带「开始分析」），但不自动开跑——用户
 * 可能只是试导入，自动花掉几十次调用不合适。
 */
export function StoryStructureCard({ project, enabled }: StoryStructureCardProps) {
  const { t } = useTranslation();
  const [started, setStarted] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const askedRef = useRef(false);

  const structureQuery = useStoryStructure(project, enabled);
  const analyze = useAnalyzeStory(project);

  const stream = useTaskStream({
    taskType: "analyze_story",
    project,
    episode: 0,
    enabled: started,
    showCompleteToast: false,
    invalidateKeys: [queryKeys.storyStructure(project)],
    onComplete: () => {
      setStarted(false);
      toast.success(t("story.completed"));
    },
    onError: (error) => {
      setStarted(false);
      toast.error(error);
    },
  });

  const handleAnalyze = useCallback(() => {
    if (started || analyze.isPending) return;
    analyze.mutate(
      { reuse: true },
      {
        onSuccess: () => setStarted(true),
        onError: (error) => toast.error(backendErrorToastMessage(error, t)),
      },
    );
  }, [analyze, started, t]);

  // 导入完成、还没有分析结果时问一次。askedRef 保证同一页面会话只问一次，
  // 否则每次重新取数都会再弹一遍。
  useEffect(() => {
    if (!enabled || askedRef.current) return;
    if (!structureQuery.isFetched || structureQuery.data) return;
    askedRef.current = true;
    toast.info(t("story.ask"), {
      duration: 12000,
      action: { label: t("story.analyze"), onClick: handleAnalyze },
    });
  }, [enabled, structureQuery.isFetched, structureQuery.data, handleAnalyze, t]);

  if (!enabled) return null;

  const structure = structureQuery.data ?? null;
  const running = started;

  return (
    <div className="rounded-lg border border-violet-300/12 bg-violet-500/[0.035] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-violet-300" />
          <div>
            <p className="text-sm font-medium text-foreground">{t("story.title")}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {structure
                ? t("story.summary", {
                    volumes: structure.volumes.length,
                    chapters: structure.total_chapters,
                  })
                : t("story.description")}
            </p>
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={running || analyze.isPending}
          onClick={handleAnalyze}
        >
          {running || analyze.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <BookOpen className="size-3.5" />
          )}
          {structure ? t("story.reanalyze") : t("story.analyze")}
        </Button>
      </div>

      {running && (
        <div className="mt-3 space-y-1.5">
          <Progress value={Math.round((stream.progress || 0) * 100)} />
          <p className="text-xs text-muted-foreground">
            {stream.currentTask || t("story.analyzing")}
          </p>
        </div>
      )}

      {!running && structure && (
        <div className="mt-3 space-y-3">
          {structure.logline && (
            <p className="text-sm text-foreground/90">{structure.logline}</p>
          )}
          {structure.mainline && (
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                {t("story.mainline")}
              </p>
              <p className="mt-1 text-sm leading-relaxed text-foreground/80">
                {structure.mainline}
              </p>
            </div>
          )}

          <div className="space-y-1.5">
            {structure.volumes.map((volume) => {
              const isOpen = expanded === volume.index;
              return (
                <div
                  key={volume.index}
                  className="rounded-md border border-white/[0.06] bg-white/[0.02]"
                >
                  <button
                    type="button"
                    onClick={() => setExpanded(isOpen ? null : volume.index)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left"
                  >
                    <ChevronDown
                      className={`size-3.5 shrink-0 text-muted-foreground transition-transform ${
                        isOpen ? "" : "-rotate-90"
                      }`}
                    />
                    <span className="text-sm font-medium text-foreground">
                      {t("story.volumeLabel", { index: volume.index })}
                      {volume.title ? ` · ${volume.title}` : ""}
                    </span>
                    <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                      {t("story.chapterRange", {
                        start: volume.chapter_start,
                        end: volume.chapter_end,
                      })}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="space-y-2 border-t border-white/[0.06] px-3 py-2">
                      {volume.stage && (
                        <p className="text-xs text-muted-foreground">{volume.stage}</p>
                      )}
                      {volume.core_conflict && (
                        <p className="text-sm text-foreground/85">
                          {volume.core_conflict}
                        </p>
                      )}
                      {volume.outline && (
                        <p className="text-sm leading-relaxed text-foreground/75">
                          {volume.outline}
                        </p>
                      )}
                      {volume.key_events.length > 0 && (
                        <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                          {volume.key_events.map((event, i) => (
                            <li key={i}>{event}</li>
                          ))}
                        </ul>
                      )}
                      {volume.foreshadowing.length > 0 && (
                        <div className="text-xs text-muted-foreground">
                          <span className="font-medium">{t("story.foreshadowing")}：</span>
                          {volume.foreshadowing.join("；")}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!running && !structure && structureQuery.isFetched && (
        <p className="mt-3 text-xs text-muted-foreground">{t("story.empty")}</p>
      )}
    </div>
  );
}
