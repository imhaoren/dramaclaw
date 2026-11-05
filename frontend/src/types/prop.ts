// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
export interface PropAsset {
  name: string;
  aliases?: string[];
  prop_type?: string;
  visual_prompt?: string;
  description?: string;
  owner?: string;
  notes?: string;
  /** 尺度锚点，如「全长约 1.1m，约到成年男性胸口」。出参考图与分镜时用它约束尺寸。 */
  scale?: string;
  reference_path?: string | null;
  reference_url?: string | null;
}

