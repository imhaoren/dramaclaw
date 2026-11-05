// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { jsonWithBackendError } from "@/lib/api-errors";
import { p } from "@/lib/api-path";
import { queryKeys } from "@/lib/query-keys";
import type { ApiResponse, ErrorResponse, TaskResponse } from "@/types/api";

/** 一卷的完整信息：分卷结论 + 展开后的大纲。 */
export interface StoryVolume {
  index: number;
  title: string;
  chapter_start: number;
  chapter_end: number;
  /** 本卷在全书中处于什么阶段，如「入门期」「势力升级」。 */
  stage: string;
  core_conflict: string;
  key_events: string[];
  cliffhanger: string;
  outline: string;
  turning_points: string[];
  foreshadowing: string[];
  characters: string[];
}

export interface StoryEpisodePlan {
  title: string;
  chapter_start: number;
  chapter_end: number;
  content_summary: string;
  main_conflict: string;
  cliffhanger: string;
  key_events: string[];
  character_names: string[];
  density: string;
}

export interface StoryStructure {
  version: string;
  generated_at: string;
  total_chapters: number;
  total_chars: number;
  /** 一句话故事。 */
  logline: string;
  /** 主线梗概。 */
  mainline: string;
  /** 全书核心人物。 */
  characters: string[];
  volumes: StoryVolume[];
  /** 按卷分集方案；未规划时为空。 */
  episode_plan: StoryEpisodePlan[];
}

export interface StoryAnalysisParams {
  reuse?: boolean;
  batch_size?: number;
  concurrency?: number;
  plan_episodes?: boolean;
  target_episodes?: number;
  chars_per_episode?: number;
  episode_counts?: number[];
}

export function useStoryStructure(project: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.storyStructure(project),
    queryFn: async () => {
      const response = await jsonWithBackendError<ApiResponse<StoryStructure | null>>(
        api.get(p`api/v1/projects/${project}/story/structure`, {
          throwHttpErrors: false,
        }),
      );
      if (!response.ok) {
        throw new Error(response.error);
      }
      return response.data;
    },
    enabled: !!project && enabled,
    staleTime: 60_000,
  });
}

/**
 * 入队一次全书结构分析。
 *
 * 这是长任务（几百章要几十次模型调用），接口只负责入队，进度走
 * `useTaskStream` 的任务流，不要在这里等它跑完。
 */
export function useAnalyzeStory(project: string) {
  return useMutation({
    mutationFn: async (params?: StoryAnalysisParams) => {
      const response = await jsonWithBackendError<TaskResponse | ErrorResponse>(
        api.post(p`api/v1/projects/${project}/story/analyze`, {
          json: params ?? { reuse: true },
          throwHttpErrors: false,
        }),
      );
      if (!response.ok) {
        throw new Error(response.error);
      }
      return response;
    },
  });
}

export interface StoryStructureUpdatePayload {
  volumes: StoryVolume[];
  logline?: string;
  mainline?: string;
}

/** 保存人工修正后的分卷结构（要求连续覆盖全部章节）。 */
export function useUpdateStoryStructure(project: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: StoryStructureUpdatePayload) => {
      const response = await jsonWithBackendError<
        { ok: true; data: StoryStructure } | ErrorResponse
      >(
        api.put(p`api/v1/projects/${project}/story/structure`, {
          json: payload,
          throwHttpErrors: false,
        }),
      );
      if (!response.ok) {
        throw new Error(response.error);
      }
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.storyStructure(project), data);
    },
  });
}
