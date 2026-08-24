"use client";

import type { DramaSourceAsset } from "@/studio/drama/types";
import type { CreativeProjectHandoff } from "@/lib/creative-runtime-contract";

export type MaterializedCreativeProject = {
    handoffId: string;
    surface: CreativeProjectHandoff["surface"];
    projectId: string;
    href: string;
    title: string;
};

const handoffInflight = new Map<string, Promise<MaterializedCreativeProject>>();

export function materializeCreativeProjectHandoff(handoff: CreativeProjectHandoff): Promise<MaterializedCreativeProject> {
    const active = handoffInflight.get(handoff.id);
    if (active) return active;
    const promise = materializeProject(handoff).finally(() => handoffInflight.delete(handoff.id));
    handoffInflight.set(handoff.id, promise);
    return promise;
}

export async function getMaterializedCreativeProject(handoff: CreativeProjectHandoff): Promise<MaterializedCreativeProject | undefined> {
    if (handoff.surface === "canvas") {
        return undefined;
    }
    const useDramaStore = await hydratedDramaStore();
    const project = useDramaStore.getState().projects.find((item) => item.sourceHandoffId === handoff.id);
    return project ? materializedProject(handoff, project.id) : undefined;
}

async function materializeProject(handoff: CreativeProjectHandoff): Promise<MaterializedCreativeProject> {
    if (handoff.surface === "canvas") {
        throw new Error("此开源版本不包含 Novo AI 自研画布实现，请改为交接到短剧项目。");
    }
    const useDramaStore = await hydratedDramaStore();
    const existing = useDramaStore.getState().projects.find((project) => project.sourceHandoffId === handoff.id);
    if (existing) return materializedProject(handoff, existing.id);
    const input = { ...buildDramaHandoffInput(handoff), sourceHandoffId: handoff.id };
    const projectId = await useDramaStore.getState().createProject(input);
    return materializedProject(handoff, projectId);
}

export function buildDramaHandoffInput(handoff: CreativeProjectHandoff) {
    const sourceAssets: DramaSourceAsset[] = handoff.assets.map((asset) => ({
        id: asset.id,
        type: asset.type,
        title: asset.title,
        textContent: asset.textContent,
        storageKey: asset.storageKey,
        remoteUrl: asset.remoteUrl,
        serverUrl: asset.serverUrl,
        mimeType: asset.mimeType,
        width: asset.width,
        height: asset.height,
    }));
    const textAssets = sourceAssets.filter((asset) => asset.type === "text" && asset.textContent?.trim());
    const initialScript = textAssets.length ? textAssets.map((asset) => `【${asset.title}】\n${asset.textContent}`).join("\n\n") : handoff.summary;
    return {
        title: handoff.title,
        summary: handoff.summary,
        style: handoff.style || "写实电影感",
        ratio: handoff.ratio || ("9:16" as const),
        initialScript,
        sourceAssets,
    };
}

function materializedProject(handoff: CreativeProjectHandoff, projectId: string): MaterializedCreativeProject {
    return { handoffId: handoff.id, surface: handoff.surface, projectId, href: `/${handoff.surface}/${projectId}`, title: handoff.title };
}

async function hydratedDramaStore() {
    const { useDramaStore } = await import("@/studio/drama/stores/use-drama-store");
    await useDramaStore.getState().hydrate();
    return useDramaStore;
}
