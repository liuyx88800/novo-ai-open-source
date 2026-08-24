import type { DramaEpisode, DramaProject } from "@/lib/drama-project-contract";

export type DramaAgentMentionKind = "character" | "scene" | "prop" | "clue" | "source" | "shot";
export type DramaAgentMentionItem = { id: string; kind: DramaAgentMentionKind; title: string; description: string; alias: string };

const KIND_LABELS: Record<DramaAgentMentionKind, string> = {
    character: "角色",
    scene: "场景",
    prop: "道具",
    clue: "线索",
    source: "来源",
    shot: "镜头",
};

export function collectDramaAgentMentionItems(project: DramaProject, episode: DramaEpisode): DramaAgentMentionItem[] {
    const items: Array<Omit<DramaAgentMentionItem, "alias">> = [
        ...(project.characters || []).map((item, index) => ({ id: safeText(item?.id, `character-${index + 1}`), kind: "character" as const, title: safeText(item?.name, `角色 ${index + 1}`), description: safeText(item?.description) })),
        ...(project.scenes || []).map((item, index) => ({ id: safeText(item?.id, `scene-${index + 1}`), kind: "scene" as const, title: safeText(item?.name, `场景 ${index + 1}`), description: safeText(item?.description) })),
        ...(project.props || []).map((item, index) => ({ id: safeText(item?.id, `prop-${index + 1}`), kind: "prop" as const, title: safeText(item?.name, `道具 ${index + 1}`), description: safeText(item?.description) })),
        ...(project.clues || []).map((item, index) => ({ id: safeText(item?.id, `clue-${index + 1}`), kind: "clue" as const, title: safeText(item?.name, `线索 ${index + 1}`), description: safeText(item?.description || item?.payoff) })),
        ...(project.sourceAssets || []).map((item, index) => ({ id: safeText(item?.id, `source-${index + 1}`), kind: "source" as const, title: safeText(item?.title, `来源 ${index + 1}`), description: safeText(item?.textContent || item?.type) })),
        ...(episode.shots || []).map((item, index) => ({ id: safeText(item?.id, `shot-${index + 1}`), kind: "shot" as const, title: safeText(item?.title, `镜头 ${String(item?.order || index + 1).padStart(2, "0")}`), description: safeText(item?.description || item?.sourceText) })),
    ];
    const counts = new Map<DramaAgentMentionKind, number>();
    const usedAliases = new Set<string>();
    return items.map((item) => {
        const ordinal = (counts.get(item.kind) || 0) + 1;
        counts.set(item.kind, ordinal);
        const preferredAlias = item.kind === "character" ? safeText(item.title).replace(/\s+/gu, "") : `${KIND_LABELS[item.kind]}${ordinal}`;
        const baseAlias = preferredAlias || `${KIND_LABELS[item.kind]}${ordinal}`;
        let alias = baseAlias;
        let duplicate = 2;
        while (usedAliases.has(alias)) alias = `${baseAlias}${duplicate++}`;
        usedAliases.add(alias);
        return { ...item, alias };
    });
}

export function dramaAgentMentionAtCursor(value: string, cursor: number) {
    const end = Math.max(0, Math.min(value.length, cursor));
    const match = value.slice(0, end).match(/@([^\s@]*)$/u);
    if (!match) return undefined;
    const start = end - match[0].length;
    if (start > 0 && /[A-Za-z0-9._%+-]/u.test(value[start - 1])) return undefined;
    return { start, end, query: match[1] || "" };
}

export function replaceDramaAgentMention(value: string, cursor: number, alias: string) {
    const range = dramaAgentMentionAtCursor(value, cursor) || { start: cursor, end: cursor };
    const before = value.slice(0, range.start);
    const after = value.slice(range.end);
    const token = `@${alias}`;
    const separator = !after || !/^[\s，。！？、；：,.!?;:）)\]}]/u.test(after) ? " " : "";
    return { value: `${before}${token}${separator}${after}`, cursor: before.length + token.length + separator.length };
}

export function dramaAgentMentionCandidates(items: DramaAgentMentionItem[], query: string) {
    const keyword = safeText(query).toLocaleLowerCase();
    if (!keyword) return items;
    return items.filter((item) => [item.alias, item.title, item.description, KIND_LABELS[item.kind]].some((value) => safeText(value).toLocaleLowerCase().includes(keyword)));
}

export function referencedDramaAgentItems(value: string, items: DramaAgentMentionItem[]) {
    return items.filter((item) => new RegExp(`(^|\\s)@${escapeRegExp(item.alias)}(?=$|[\\s，。！？、；：,.!?;:）)\\]}])`, "u").test(value));
}

export function dramaAgentMentionKindLabel(kind: DramaAgentMentionKind) {
    return KIND_LABELS[kind];
}

function escapeRegExp(value: string) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function safeText(value: unknown, fallback = "") {
    return typeof value === "string" ? value.trim() || fallback : fallback;
}
