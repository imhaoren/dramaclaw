// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BookOpen,
  Check,
  ChevronDown,
  Download,
  Layers,
  Loader2,
  Pencil,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { queryKeys } from "@/lib/query-keys";
import {
  useStoryStructure,
  useAnalyzeStory,
  useUpdateStoryStructure,
  type StoryAnalysisParams,
  type StoryVolume,
} from "@/lib/queries/story";
import { usePlanEpisodes } from "@/lib/queries/episodes";
import { useTasks } from "@/lib/queries/tasks";
import { useTaskStream } from "@/hooks/use-task-stream";
import { backendErrorToastMessage } from "@/lib/api-errors";
import { downloadUrlAsFile } from "@/lib/browserDownload";
import { p } from "@/lib/api-path";

interface StoryStructureCardProps {
  project: string;
  /** 只有导入完成的项目才值得分析，未导入时不渲染。 */
  enabled: boolean;
}

const ACTIVE_TASK_STATUSES = new Set([
  "submitting",
  "queued",
  "pending",
  "starting",
  "running",
]);

/**
 * 全书结构分析卡片。
 *
 * 导入完成后自动入队一次结构分析：章节摘要 → 分卷 → 卷大纲（可选同时
 * 规划分集）。任务进度走任务流实时展示；结果可逐卷展开、人工修正并导出。
 */
export function StoryStructureCard({ project, enabled }: StoryStructureCardProps) {
  const { t } = useTranslation();
  const [started, setStarted] = useState(false);
  const [planningStarted, setPlanningStarted] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<StoryVolume[] | null>(null);
  const [targetEpisodes, setTargetEpisodes] = useState(12);
  const autoStartedRef = useRef(false);

  const structureQuery = useStoryStructure(project, enabled);
  const tasksQuery = useTasks({ project, episode: 0 });
  const analyze = useAnalyzeStory(project);
  const updateStructure = useUpdateStoryStructure(project);
  const planEpisodes = usePlanEpisodes(project);

  const structure = structureQuery.data ?? null;
  const structureVolumes = structure?.volumes ?? [];
  const episodePlan = structure?.episode_plan ?? [];

  const analyzeRunning = Boolean(
    tasksQuery.data?.data.some(
      (task) =>
        task.task_type === "analyze_story" && ACTIVE_TASK_STATUSES.has(task.status),
    ),
  );
  const planRunning = Boolean(
    tasksQuery.data?.data.some(
      (task) =>
        task.task_type === "build_episodes" && ACTIVE_TASK_STATUSES.has(task.status),
    ),
  );

  const analyzeStream = useTaskStream({
    taskType: "analyze_story",
    project,
    episode: 0,
    enabled: started || analyzeRunning,
    showCompleteToast: false,
    invalidateKeys: [queryKeys.storyStructure(project), queryKeys.tasks(project)],
    onComplete: () => {
      setStarted(false);
      toast.success(t("story.completed"));
    },
    onError: (error) => {
      setStarted(false);
      toast.error(error);
    },
  });

  const planStream = useTaskStream({
    taskType: "build_episodes",
    project,
    episode: 0,
    enabled: planningStarted || planRunning,
    showCompleteToast: false,
    invalidateKeys: [
      queryKeys.storyStructure(project),
      queryKeys.episodes(project),
      queryKeys.tasks(project),
    ],
    onComplete: () => {
      setPlanningStarted(false);
      toast.success(t("story.episodesCompleted"));
    },
    onError: (error) => {
      setPlanningStarted(false);
      toast.error(error);
    },
  });

  const handleAnalyze = useCallback(
    (options?: StoryAnalysisParams) => {
      if (started || analyze.isPending || analyzeRunning) return;
      analyze.mutate(options ?? { reuse: true }, {
        onSuccess: () => setStarted(true),
        onError: (error) => toast.error(backendErrorToastMessage(error, t)),
      });
    },
    [analyze, started, analyzeRunning, t],
  );

  // 导入完成且还没有结构结果时自动开始分析。同一浏览器会话只自动触发一次，
  // 避免每次刷新都重新扣费；任务已在跑时直接挂上进度流，不重复入队。
  useEffect(() => {
    if (!enabled || autoStartedRef.current) return;
    if (!structureQuery.isFetched || structureQuery.data) return;
    if (!tasksQuery.isFetched) return;
    autoStartedRef.current = true;
    if (analyzeRunning) {
      setStarted(true);
      return;
    }
    toast.info(t("story.autoStarted"));
    // 自动跑完整链路：解析 → 分卷/大纲 → 按卷分集。
    handleAnalyze({
      reuse: true,
      plan_episodes: true,
      target_episodes: targetEpisodes,
    });
  }, [
    enabled,
    structureQuery.isFetched,
    structureQuery.data,
    tasksQuery.isFetched,
    analyzeRunning,
    handleAnalyze,
    t,
  ]);

  const handlePlanEpisodes = useCallback(() => {
    if (planningStarted || planEpisodes.isPending || planRunning) return;
    planEpisodes.mutate(
      {
        planning_mode: "volumes",
        target_episodes: Math.max(1, targetEpisodes),
      },
      {
        onSuccess: () => setPlanningStarted(true),
        onError: (error) => toast.error(backendErrorToastMessage(error, t)),
      },
    );
  }, [planningStarted, planEpisodes, planRunning, targetEpisodes, t]);

  const beginEdit = useCallback(() => {
    setDraft(structuredClone(structureVolumes));
    setEditing(true);
  }, [structureVolumes]);

  const cancelEdit = useCallback(() => {
    setDraft(null);
    setEditing(false);
  }, []);

  const saveEdit = useCallback(() => {
    if (!draft) return;
    updateStructure.mutate(
      { volumes: draft, logline: structure?.logline, mainline: structure?.mainline },
      {
        onSuccess: () => {
          setEditing(false);
          setDraft(null);
          toast.success(t("story.editSaved"));
        },
        onError: (error) => toast.error(backendErrorToastMessage(error, t)),
      },
    );
  }, [draft, updateStructure, structure, t]);

  const updateDraftVolume = useCallback(
    (index: number, patch: Partial<StoryVolume>) => {
      setDraft((current) =>
        current
          ? current.map((volume) =>
              volume.index === index ? { ...volume, ...patch } : volume,
            )
          : current,
      );
    },
    [],
  );

  const exportStructure = useCallback(() => {
    downloadUrlAsFile(
      `${p`api/v1/projects/${project}/story/structure/export`}?format=markdown`,
      `${project}-story-structure.md`,
    ).catch(() => toast.error(t("story.exportFailed")));
  }, [project, t]);

  const exportEpisodes = useCallback(() => {
    downloadUrlAsFile(
      `${p`api/v1/projects/${project}/episodes/export`}?format=markdown`,
      `${project}-episodes.md`,
    ).catch(() => toast.error(t("story.exportFailed")));
  }, [project, t]);

  const episodesByVolume = useMemo(() => {
    const grouped = new Map<number, typeof episodePlan>();
    for (const episode of episodePlan) {
      for (const volume of structureVolumes) {
        if (
          episode.chapter_start <= volume.chapter_end &&
          episode.chapter_end >= volume.chapter_start
        ) {
          const list = grouped.get(volume.index) ?? [];
          list.push(episode);
          grouped.set(volume.index, list);
        }
      }
    }
    return grouped;
  }, [episodePlan, structureVolumes]);

  if (!enabled) return null;

  const running = started || analyzeRunning;
  const planning = planningStarted || planRunning;
  const progress = running ? analyzeStream.progress : planStream.progress;
  const currentTask = running ? analyzeStream.currentTask : planStream.currentTask;

  return (
    <div className="rounded-lg border border-violet-300/12 bg-violet-500/[0.035] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-violet-300" />
          <div>
            <p className="text-sm font-medium text-foreground">{t("story.title")}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {structure
                ? t("story.summaryWithEpisodes", {
                    volumes: structure.volumes.length,
                    chapters: structure.total_chapters,
                    episodes: episodePlan.length,
                  })
                : t("story.description")}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {structure && (
            <>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={exportStructure}
                aria-label={t("story.exportStructure")}
              >
                <Download className="size-3.5" />
                {t("story.exportStructure")}
              </Button>
              {episodePlan.length > 0 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={exportEpisodes}
                >
                  <Download className="size-3.5" />
                  {t("story.exportEpisodes")}
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={editing ? cancelEdit : beginEdit}
                disabled={running || planning}
              >
                {editing ? <X className="size-3.5" /> : <Pencil className="size-3.5" />}
                {editing ? t("story.cancelEdit") : t("story.editVolumes")}
              </Button>
            </>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={running || planning || analyze.isPending}
            onClick={() => handleAnalyze({ reuse: true })}
          >
            {running ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <BookOpen className="size-3.5" />
            )}
            {structure ? t("story.reanalyze") : t("story.analyze")}
          </Button>
        </div>
      </div>

      {(running || planning) && (
        <div className="mt-3 space-y-1.5">
          <Progress value={Math.round((progress || 0) * 100)} />
          <p className="text-xs text-muted-foreground">
            {currentTask || (planning ? t("story.planning") : t("story.analyzing"))}
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
          {structure.characters?.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                {t("story.characters")}
              </p>
              <p className="mt-1 text-sm leading-relaxed text-foreground/80">
                {structure.characters.join("、")}
              </p>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 rounded-md border border-white/[0.06] bg-white/[0.02] px-3 py-2">
            <Layers className="size-3.5 text-violet-300" />
            <span className="text-xs text-muted-foreground">
              {t("story.episodePlanLabel", { count: episodePlan.length })}
            </span>
            <div className="ml-auto flex items-center gap-2">
              <Input
                type="number"
                min={1}
                max={2000}
                value={targetEpisodes}
                onChange={(event) =>
                  setTargetEpisodes(Math.max(1, Number(event.target.value) || 1))
                }
                className="h-7 w-20 text-xs"
                aria-label={t("story.targetEpisodes")}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={planning || running || planEpisodes.isPending}
                onClick={handlePlanEpisodes}
              >
                {planning ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Layers className="size-3.5" />
                )}
                {episodePlan.length > 0
                  ? t("story.replanEpisodes")
                  : t("story.planEpisodes")}
              </Button>
            </div>
          </div>

          <div className="space-y-1.5">
            {(editing ? draft ?? [] : structureVolumes).map((volume) => {
              const isOpen = expanded === volume.index && !editing;
              const episodes = episodesByVolume.get(volume.index) ?? [];
              return (
                <div
                  key={volume.index}
                  className="rounded-md border border-white/[0.06] bg-white/[0.02]"
                >
                  {editing ? (
                    <div className="space-y-2 px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-medium text-muted-foreground">
                          {t("story.volumeLabel", { index: volume.index })}
                        </span>
                        <Input
                          value={volume.title}
                          onChange={(event) =>
                            updateDraftVolume(volume.index, { title: event.target.value })
                          }
                          className="h-7 flex-1 text-xs"
                          placeholder={t("story.volumeTitle")}
                        />
                        <Input
                          type="number"
                          value={volume.chapter_start}
                          onChange={(event) =>
                            updateDraftVolume(volume.index, {
                              chapter_start: Number(event.target.value),
                            })
                          }
                          className="h-7 w-20 text-xs"
                          aria-label={t("story.chapterStart")}
                        />
                        <span className="text-xs text-muted-foreground">–</span>
                        <Input
                          type="number"
                          value={volume.chapter_end}
                          onChange={(event) =>
                            updateDraftVolume(volume.index, {
                              chapter_end: Number(event.target.value),
                            })
                          }
                          className="h-7 w-20 text-xs"
                          aria-label={t("story.chapterEnd")}
                        />
                      </div>
                      <Input
                        value={volume.stage}
                        onChange={(event) =>
                          updateDraftVolume(volume.index, { stage: event.target.value })
                        }
                        className="h-7 text-xs"
                        placeholder={t("story.stage")}
                      />
                      <Input
                        value={volume.core_conflict}
                        onChange={(event) =>
                          updateDraftVolume(volume.index, {
                            core_conflict: event.target.value,
                          })
                        }
                        className="h-7 text-xs"
                        placeholder={t("story.coreConflict")}
                      />
                      <textarea
                        value={volume.outline}
                        onChange={(event) =>
                          updateDraftVolume(volume.index, { outline: event.target.value })
                        }
                        className="min-h-20 w-full rounded-md border border-white/10 bg-transparent px-2 py-1.5 text-xs text-foreground outline-none focus:border-violet-300/40"
                        placeholder={t("story.outline")}
                      />
                    </div>
                  ) : (
                    <>
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
                        {episodes.length > 0 && (
                          <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] text-violet-200">
                            {t("story.episodeCount", { count: episodes.length })}
                          </span>
                        )}
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
                              <span className="font-medium">
                                {t("story.foreshadowing")}：
                              </span>
                              {volume.foreshadowing.join("；")}
                            </div>
                          )}
                          {episodes.length > 0 && (
                            <div className="space-y-1 border-t border-white/[0.06] pt-2">
                              <p className="text-xs font-medium text-muted-foreground">
                                {t("story.volumeEpisodes")}
                              </p>
                              {episodes.map((episode, i) => (
                                <div
                                  key={`${episode.chapter_start}-${episode.chapter_end}-${i}`}
                                  className="rounded border border-white/[0.04] px-2 py-1.5"
                                >
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium text-foreground">
                                      {episode.title || t("story.untitledEpisode")}
                                    </span>
                                    <span className="ml-auto text-[10px] text-muted-foreground">
                                      {t("story.chapterRange", {
                                        start: episode.chapter_start,
                                        end: episode.chapter_end,
                                      })}
                                    </span>
                                  </div>
                                  {(episode.content_summary || episode.main_conflict) && (
                                    <p className="mt-0.5 text-[11px] leading-relaxed text-foreground/70">
                                      {episode.content_summary || episode.main_conflict}
                                    </p>
                                  )}
                                  {episode.cliffhanger && (
                                    <p className="mt-0.5 text-[11px] text-amber-200/80">
                                      {t("story.cliffhanger")}：{episode.cliffhanger}
                                    </p>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>

          {editing && (
            <div className="flex items-center gap-2">
              <Button type="button" size="sm" onClick={saveEdit} disabled={updateStructure.isPending}>
                {updateStructure.isPending ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Check className="size-3.5" />
                )}
                {t("story.saveEdit")}
              </Button>
              <p className="text-xs text-muted-foreground">{t("story.editHint")}</p>
            </div>
          )}
        </div>
      )}

      {!running && !structure && structureQuery.isFetched && (
        <p className="mt-3 text-xs text-muted-foreground">{t("story.empty")}</p>
      )}
    </div>
  );
}
