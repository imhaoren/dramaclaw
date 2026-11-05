// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Package, Plus, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AssetHeaderActions } from "@/components/assets/asset-header-actions-slot";
import { CharacterImageSourceSelect } from "@/components/assets/character-image-source-select";
import { CreditCostInline } from "@/components/credit-cost-inline";
import { PropAssetCard } from "@/components/assets/prop-asset-card";
import { Progress } from "@/components/ui/progress";
import { AssetBeatReferences } from "@/components/assets/asset-beat-references";
import {
  AssetResultCount,
  AssetSearchBox,
  filterBySearch,
} from "@/components/assets/asset-search-box";
import {
  useAssetReferences,
  type BeatReference,
} from "@/lib/queries/asset-references";
import { useGenerationCreditCost } from "@/lib/queries/generation-credit-cost";
import { useAssetImageSourceSelection } from "@/lib/queries/character-image-selection";
import { useAssetFocus } from "@/hooks/use-asset-focus";
import { Button } from "@/components/ui/button";
import { HeaderRefreshButton } from "@/components/ui/header-refresh-button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { EMPTY_STATE_ACTION_BUTTON_CLASS } from "@/components/ui/empty-state-styles";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useTaskController } from "@/hooks/use-task-controller";
import { useTaskStream } from "@/hooks/use-task-stream";
import { useTaskActivity } from "@/task-center/use-task-activity";
import { propReferenceAssetScope } from "@/lib/task-scope";
import {
  backendErrorResponseToastMessage,
  backendErrorToastMessage,
  BillingRuleNotConfiguredError,
  taskResponseToastMessage,
} from "@/lib/api-errors";
import {
  useBuildProps,
  useCreateProp,
  useDeleteProp,
  useGeneratePropReferenceAsync,
  useProps,
  useUpdateProp,
  useUploadPropReference,
  type PropPayload,
} from "@/lib/queries/props";
import { openPresetProjectionInMyCanvas } from "@/features/freezone/openPresetProjection";
import { queryKeys } from "@/lib/query-keys";
import { confirmAssetRename } from "@/lib/confirm-asset-rename";
import type { ErrorResponse } from "@/types/api";
import type { PropAsset } from "@/types/prop";

const PROP_FORM_DEFAULT: PropPayload = {
  name: "",
  prop_type: "object",
  visual_prompt: "",
  description: "",
  owner: "",
  scale: "",
};

const PROP_TYPE_VALUES = [
  "weapon",
  "accessory",
  "artifact",
  "document",
  "furniture",
  "object",
] as const;

function isErrorResponse(value: unknown): value is ErrorResponse {
  return Boolean(value && typeof value === "object" && (value as { ok?: unknown }).ok === false);
}

async function openPropFreezoneCanvas(project: string, propName: string) {
  await openPresetProjectionInMyCanvas(project, {
    scope: "asset",
    asset_kind: "prop",
    asset_id: propName,
  });
}

function PropDialog({
  open,
  initial,
  project,
  references,
  onOpenChange,
  onSubmit,
  saving,
}: {
  open: boolean;
  initial: PropAsset | null;
  project: string;
  references: BeatReference[];
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: PropPayload) => Promise<void>;
  saving: boolean;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<PropPayload>(PROP_FORM_DEFAULT);

  useEffect(() => {
    setDraft(
      initial
        ? {
            name: initial.name,
            aliases: initial.aliases ?? [],
            prop_type: initial.prop_type ?? "object",
            visual_prompt: initial.visual_prompt ?? "",
            description: initial.description ?? "",
            owner: initial.owner ?? "",
            notes: initial.notes ?? "",
            scale: initial.scale ?? "",
          }
        : PROP_FORM_DEFAULT,
    );
  }, [initial, open]);

  const title = initial ? t("assets.props.editProp") : t("assets.props.newProp");
  const PROP_DIALOG_INPUT_CLASS = "h-11 rounded-[8px] border-white/12 bg-white/[0.04] px-3 text-sm placeholder:text-muted-foreground/70 focus-visible:border-white/25 focus-visible:ring-2 focus-visible:ring-white/8 dark:bg-white/[0.04]";
  const PROP_DIALOG_TEXTAREA_CLASS = "rounded-[8px] border-white/12 bg-white/[0.04] px-3 py-2 text-sm placeholder:text-muted-foreground/70 focus-visible:border-white/25 focus-visible:ring-2 focus-visible:ring-white/8 dark:bg-white/[0.04]";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 overflow-hidden rounded-2xl border border-white/8 bg-background/68 p-7 shadow-none backdrop-blur-3xl sm:max-w-lg">
        <DialogHeader className="gap-2">
          <DialogTitle className="flex items-center gap-2 text-lg font-medium tracking-tight">
            <span>{title}</span>
          </DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label className="text-sm">{t("assets.props.fields.name")}</Label>
            <Input
              value={draft.name}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, name: event.target.value }))
              }
              className={PROP_DIALOG_INPUT_CLASS}
            />
          </div>
          <div className="grid gap-2">
            <Label className="text-sm">{t("assets.props.fields.type")}</Label>
            <Select
              value={draft.prop_type || "object"}
              onValueChange={(value) =>
                setDraft((prev) => ({ ...prev, prop_type: String(value) }))
              }
            >
              <SelectTrigger className={PROP_DIALOG_INPUT_CLASS}>
                <SelectValue>
                  {t(`assets.props.types.${draft.prop_type || "object"}`, {
                    defaultValue: draft.prop_type || "object",
                  })}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {PROP_TYPE_VALUES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(`assets.props.types.${value}`, { defaultValue: value })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label className="text-sm">{t("assets.props.fields.owner")}</Label>
            <Input
              value={draft.owner ?? ""}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, owner: event.target.value }))
              }
              className={PROP_DIALOG_INPUT_CLASS}
            />
          </div>
          <div className="grid gap-2">
            <Label className="text-sm">{t("assets.props.fields.visualPrompt")}</Label>
            <Textarea
              rows={4}
              value={draft.visual_prompt ?? ""}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, visual_prompt: event.target.value }))
              }
              className={PROP_DIALOG_TEXTAREA_CLASS}
            />
          </div>
          <div className="grid gap-2">
            <Label className="text-sm">{t("assets.props.fields.scale")}</Label>
            <Input
              value={draft.scale ?? ""}
              placeholder={t("assets.props.scalePlaceholder")}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, scale: event.target.value }))
              }
              className={PROP_DIALOG_INPUT_CLASS}
            />
            <p className="text-xs leading-5 text-muted-foreground">
              {t("assets.props.scaleHint")}
            </p>
          </div>
          {initial && (
            <AssetBeatReferences
              project={project}
              references={references}
              className="border-t border-border/60 pt-4"
            />
          )}
        </div>
        <DialogFooter className="-mx-7 -mb-7 border-t-0 bg-transparent p-7 pt-3 sm:flex-row sm:justify-end">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            className="h-10 w-18 rounded-md border-white/18 bg-white/[0.06] px-0 text-sm font-normal text-foreground/80 hover:border-white/28 hover:bg-white/[0.1] hover:text-foreground"
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={() => onSubmit(draft)}
            disabled={saving || !draft.name.trim()}
            className="h-10 w-18 rounded-md bg-primary px-0 text-sm font-normal text-primary-foreground shadow-lg shadow-primary/15 hover:bg-primary/90"
          >
            {saving && <Loader2 className="size-4 animate-spin" />}
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PropAssetCardController({
  project,
  prop,
  imageSourceSelection,
  onEdit,
  onDelete,
}: {
  project: string;
  prop: PropAsset;
  imageSourceSelection: string;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const generateReference = useGeneratePropReferenceAsync(project, prop.name);
  const uploadReference = useUploadPropReference(project, prop.name);
  const referenceCost = useGenerationCreditCost(
    "feature",
    "mainline.prop_reference_image",
    {
      surface: "supertale",
      params: imageSourceSelection ? { image_selection: imageSourceSelection } : null,
    },
  );
  const referenceCostDisplay =
    referenceCost.data?.data.display ??
    (referenceCost.error instanceof BillingRuleNotConfiguredError
      ? t("common.billingRuleNotConfiguredShort")
      : undefined);
  const [freezonePending, setFreezonePending] = useState(false);
  const refTask = useTaskController({
    key: {
      taskType: "prop_reference_asset",
      project,
      episode: 0,
      // Must match the BE-hashed scope (see task-scope.ts), else the button
      // loses its loading state after a refresh.
      scope: propReferenceAssetScope(prop.name),
    },
    invalidateKeys: [queryKeys.props(project)],
  });

  async function handleGenerate() {
    try {
      const res = await generateReference.mutateAsync({ model: imageSourceSelection });
      if (isErrorResponse(res)) {
        toast.error(res.error);
        return;
      }
      refTask.start({ scope: res.scope });
    } catch (err) {
      toast.error(backendErrorToastMessage(err, t));
    }
  }

  async function handleOpenFreezone() {
    setFreezonePending(true);
    try {
      await openPropFreezoneCanvas(project, prop.name);
      toast.success(t("assets.props.freezoneOpened"));
    } catch {
      toast.error(t("assets.props.freezoneOpenFailed"));
    } finally {
      setFreezonePending(false);
    }
  }

  async function handleUpload(file: File) {
    const res = await uploadReference.mutateAsync(file);
    if (isErrorResponse(res)) {
      toast.error(res.error);
      return;
    }
    toast.success(t("assets.props.uploadReferenceSuccess"));
  }

  return (
    <PropAssetCard
      prop={prop}
      generating={generateReference.isPending || refTask.started}
      uploading={uploadReference.isPending}
      referenceCost={referenceCostDisplay}
      referencePromotion={referenceCost.data?.data.promotion}
      freezonePending={freezonePending}
      onEdit={onEdit}
      onDelete={onDelete}
      onGenerateReference={handleGenerate}
      onUploadReference={handleUpload}
      onOpenFreezone={handleOpenFreezone}
    />
  );
}

export function PropsPanel({
  project,
  focusId,
}: {
  project: string;
  focusId?: string | null;
}) {
  const { t } = useTranslation();
  const props = useProps(project);
  const buildProps = useBuildProps(project);
  // loading 绑任务中心而不是 mutation.isPending：入队那次 POST 一返回就结束，
  // 真正的抽取在后台跑，刷新后也只有任务中心还认得它。
  const buildActivity = useTaskActivity("build_props", { episode: 0 });
  const isBuilding = buildProps.isPending || buildActivity.isActive;
  // 补水完成前 isActive 不可信，按钮先禁用，避免硬刷新后重复入队。
  const buildDisabled = isBuilding || buildActivity.isRestoring;
  const buildCost = useGenerationCreditCost("feature", "mainline.build_props");
  const buildCostDisplay =
    buildCost.data?.data.display ??
    (buildCost.error instanceof BillingRuleNotConfiguredError
      ? t("common.billingRuleNotConfiguredShort")
      : null);
  // SSE 只用来拿细粒度进度/步骤文案，并在完成时刷新道具列表；活跃与否由任务中心裁决。
  const buildStream = useTaskStream({
    taskType: "build_props",
    project,
    episode: 0,
    enabled: buildActivity.isActive,
    invalidateKeys: [queryKeys.props(project)],
  });
  const buildProgress =
    buildStream.status === "idle" ? buildActivity.progress : buildStream.progress;
  const buildLabel = buildStream.currentTask || buildActivity.currentTask;
  const createProp = useCreateProp(project);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<PropAsset | null>(null);
  const saveInFlight = useRef(false);
  const updateProp = useUpdateProp(project, editing?.name ?? "");
  const deleteProp = useDeleteProp(project);
  // Beat references are edit-only: opening the asset page must not scan every
  // beat merely to decorate cards with a usage count.
  const refDetail = useAssetReferences(
    project,
    useMemo(
      () => (editing ? [{ type: "prop" as const, id: editing.name }] : []),
      [editing],
    ),
  );
  const imageSourceQuery = useAssetImageSourceSelection(project, "prop");
  const imageSourceSelection = imageSourceQuery.data?.data.image_source_selection ?? "";
  const allItems = props.data?.data ?? [];
  const [searchQuery, setSearchQuery] = useState("");
  const items = useMemo(() => {
    const filtered = filterBySearch(allItems, searchQuery, (prop) => [
      prop.name,
      prop.prop_type,
      prop.description,
      prop.visual_prompt,
      prop.owner,
      ...(prop.aliases ?? []),
    ]);
    return filtered.sort((a, b) => a.name.localeCompare(b.name));
  }, [allItems, searchQuery]);
  const gridRef = useAssetFocus(focusId, !props.isLoading && items.length > 0);

  // SSE 断开或页面重进时 completion 事件可能收不到；任务中心一旦判定结束就补一次
  // 拉取，否则用户会看到「生成完成但列表还是空的」。
  const wasBuilding = useRef(false);
  useEffect(() => {
    if (wasBuilding.current && !buildActivity.isActive) void props.refetch();
    wasBuilding.current = buildActivity.isActive;
  }, [buildActivity.isActive, props.refetch]);

  async function handleSave(data: PropPayload) {
    // isPending only starts after confirmation; guard the entire save attempt.
    if (saveInFlight.current) return;
    saveInFlight.current = true;
    try {
      const payload = { ...data, name: data.name.trim() };
      if (editing && payload.name !== editing.name) {
        const confirmed = await confirmAssetRename(t);
        if (!confirmed) return;
      }
      const res = editing
        ? await updateProp.mutateAsync(payload)
        : await createProp.mutateAsync(payload);
      if (isErrorResponse(res)) {
        toast.error(res.error);
        return;
      }
      setDialogOpen(false);
      setEditing(null);
    } finally {
      saveInFlight.current = false;
    }
  }

  async function handleDelete(prop: PropAsset) {
    if (!window.confirm(t("assets.props.confirmDelete", { name: prop.name }))) return;
    const res = await deleteProp.mutateAsync(prop.name);
    if (isErrorResponse(res)) {
      toast.error(res.error);
      return;
    }
    toast.success(t("assets.props.deleted"));
  }

  async function handleBuildProps() {
    let res;
    try {
      res = await buildProps.mutateAsync();
    } catch (err) {
      toast.error(backendErrorToastMessage(err, t));
      return;
    }
    if (isErrorResponse(res)) {
      toast.error(backendErrorResponseToastMessage(res, t));
      return;
    }
    buildActivity.markStarted({ taskId: res.task_id });
    toast.success(taskResponseToastMessage(res, t));
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background">
      <AssetHeaderActions>
        <CharacterImageSourceSelect project={project} kind="prop" />
        <HeaderRefreshButton
          label={t("common.refresh")}
          onRefresh={async () => {
            const result = await props.refetch();
            if (result.isError) {
              toast.error(t("common.error"));
              return false;
            }
            return true;
          }}
          refreshing={props.isRefetching}
          data-props-refresh
        />
        <TooltipProvider delay={80}>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  size="sm"
                  onClick={() => {
                    setEditing(null);
                    setDialogOpen(true);
                  }}
                  className="h-8 gap-1.5 rounded-[8px] bg-primary px-3 text-xs font-normal text-primary-foreground shadow-none hover:bg-primary/85 active:bg-primary/75"
                />
              }
            >
              <Plus className="size-3.5" />
              {t("assets.props.newProp")}
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {t("assets.props.newPropHint")}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <TooltipProvider delay={80}>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  size="sm"
                  onClick={handleBuildProps}
                  disabled={buildDisabled}
                  className="h-8 gap-1.5 rounded-[8px] bg-primary px-3 text-xs font-normal text-primary-foreground shadow-none hover:bg-primary/85 active:bg-primary/75"
                />
              }
            >
              {isBuilding ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Sparkles className="size-3.5" />
              )}
              {t("assets.props.build")}
              <CreditCostInline
                display={buildCostDisplay}
                promotion={buildCost.data?.data.promotion}
                className="text-primary-foreground"
                iconClassName="text-primary-foreground drop-shadow-none [&_path]:fill-current"
              />
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {t("assets.props.buildHint")}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </AssetHeaderActions>
      <div className="min-h-0 flex-1 overflow-auto p-6">
        {!props.isLoading && allItems.length > 0 && (
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
              <AssetSearchBox
                value={searchQuery}
                onValueChange={setSearchQuery}
                placeholder={t("assets.common.searchProps")}
                ariaLabel={t("assets.common.searchProps")}
              />
            </div>
            <AssetResultCount
              resultCount={items.length}
              totalCount={allItems.length}
            />
          </div>
        )}
        {isBuilding && allItems.length > 0 && (
          <div className="mb-4 rounded-[8px] bg-white/[0.05] p-3">
            <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <span className="min-w-0 truncate">
                {buildLabel || t("assets.props.building")}
              </span>
              <span className="shrink-0 font-mono tabular-nums text-foreground/80">
                {Math.round(buildProgress * 100)}%
              </span>
            </div>
            <Progress value={buildProgress * 100} className="mt-3 h-1.5" />
          </div>
        )}
        {props.isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            {t("common.loading")}
          </div>
        ) : allItems.length === 0 && isBuilding ? (
          // 首次生成时列表本来就是空的，不给「正在生成」的反馈，用户会以为点了没反应。
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 flex size-12 items-center justify-center rounded-full border border-border bg-card">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
            <div>
              <h3 className="mb-1.5 text-sm font-semibold text-foreground">
                {t("assets.props.buildingEmpty.title")}
              </h3>
              <p className="max-w-[16rem] text-xs leading-5 text-muted-foreground">
                {t("assets.props.buildingEmpty.description")}
              </p>
            </div>
            <div className="mt-4 w-full max-w-[220px] rounded-[8px] bg-white/[0.05] p-3">
              <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                <span className="min-w-0 truncate">
                  {buildLabel || t("assets.props.building")}
                </span>
                <span className="shrink-0 font-mono tabular-nums text-foreground/80">
                  {Math.round(buildProgress * 100)}%
                </span>
              </div>
              <Progress value={buildProgress * 100} className="mt-3 h-1.5" />
            </div>
          </div>
        ) : allItems.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 flex size-12 items-center justify-center rounded-full border border-border bg-card">
              <Package className="size-5 text-muted-foreground" />
            </div>
            <div>
              <h3 className="mb-1.5 text-sm font-semibold text-foreground">
                {t("assets.props.emptyTitle")}
              </h3>
              <p className="max-w-[16rem] text-xs leading-5 text-muted-foreground">
                {t("assets.props.emptyDescription")}
              </p>
            </div>
            <div className="mt-4 flex flex-col items-center gap-2 sm:flex-row">
              <Button
                size="sm"
                onClick={handleBuildProps}
                disabled={buildDisabled}
                className="h-9 gap-1.5 rounded-[8px] bg-primary px-3 text-xs font-normal text-primary-foreground shadow-none hover:bg-primary/85 active:bg-primary/75"
              >
                <Sparkles className="size-3.5" />
                {t("assets.props.build")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEditing(null);
                  setDialogOpen(true);
                }}
                className={EMPTY_STATE_ACTION_BUTTON_CLASS}
              >
                <Plus className="size-3.5" />
                {t("assets.props.newProp")}
              </Button>
            </div>
          </div>
        ) : items.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {t("assets.common.noMatch")}
          </div>
        ) : (
          <div
            ref={gridRef}
            className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
          >
            {items.map((prop) => (
              <div key={prop.name} data-asset-id={prop.name}>
                <PropAssetCardController
                  project={project}
                  prop={prop}
                  imageSourceSelection={imageSourceSelection}
                  onEdit={() => {
                    setEditing(prop);
                    setDialogOpen(true);
                  }}
                  onDelete={() => handleDelete(prop)}
                />
              </div>
            ))}
          </div>
        )}
      </div>
      <PropDialog
        open={dialogOpen}
        initial={editing}
        project={project}
        references={
          editing ? refDetail.referencesFor("prop", editing.name) : []
        }
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) setEditing(null);
        }}
        onSubmit={handleSave}
        saving={createProp.isPending || updateProp.isPending}
      />
    </div>
  );
}
