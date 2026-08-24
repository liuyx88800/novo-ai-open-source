"use client";

import { App, Button, Tag, Tooltip } from "antd";
import { ArrowLeft, Copy, Eye, Film, Heart, Image as ImageIcon, Link2, LoaderCircle, Music2, UserPlus, UserCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useCopyText } from "@/hooks/use-copy-text";
import { getPublicWorkPublication, recordPublicWorkPublicationView, type PublicWorkPublication } from "@/services/api/work-publications";
import { getWorkCommunity, setWorkAuthorFollow, setWorkLike, type WorkCommunitySummary } from "@/services/api/work-community";
import { useRouter, useParams } from "@/studio/next-shim";

export default function SharePage() {
    const { slug } = useParams<{ slug: string }>();
    const router = useRouter();
    const { message } = App.useApp();
    const copyText = useCopyText();
    const [work, setWork] = useState<PublicWorkPublication | null>(null);
    const [community, setCommunity] = useState<WorkCommunitySummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    const load = useCallback(async () => {
        if (!slug) return;
        setLoading(true);
        setError("");
        try {
            const [workData, communityData] = await Promise.all([getPublicWorkPublication(slug), getWorkCommunity(slug).catch(() => null)]);
            setWork(workData);
            setCommunity(communityData);
            void recordPublicWorkPublicationView(slug).catch(() => undefined);
        } catch (loadError) {
            setError(loadError instanceof Error ? loadError.message : "作品加载失败");
        } finally {
            setLoading(false);
        }
    }, [slug]);

    useEffect(() => {
        void load();
    }, [load]);

    const toggleLike = async () => {
        if (!work || !community) return;
        const next = !community.liked;
        try {
            const result = await setWorkLike(work.slug, next);
            setCommunity({ ...community, liked: result.active, likeCount: result.likeCount });
        } catch (likeError) {
            message.error(likeError instanceof Error ? likeError.message : "操作失败");
        }
    };

    const toggleFollow = async () => {
        if (!work || !community) return;
        const next = !community.followingAuthor;
        try {
            const result = await setWorkAuthorFollow(work.slug, next);
            setCommunity({ ...community, followingAuthor: result.active, followerCount: result.followerCount });
        } catch (followError) {
            message.error(followError instanceof Error ? followError.message : "操作失败");
        }
    };

    if (loading) {
        return (
            <main className="grid min-h-screen place-items-center bg-[#f7f8fa] text-sm text-stone-500 dark:bg-[#0f1114] dark:text-stone-400">
                <span className="flex items-center gap-2">
                    <LoaderCircle className="size-4 animate-spin" /> 正在加载作品
                </span>
            </main>
        );
    }

    if (error || !work) {
        return (
            <main className="grid min-h-screen place-items-center bg-[#f7f8fa] px-6 text-center text-stone-600 dark:bg-[#0f1114] dark:text-stone-300">
                <div>
                    <p className="text-base font-medium">{error || "作品不存在或已停止公开"}</p>
                    <Button className="mt-4" icon={<ArrowLeft className="size-4" />} onClick={() => router.push("/agent")}>
                        返回首页
                    </Button>
                </div>
            </main>
        );
    }

    const cover = work.assets.find((asset) => asset.role === "cover" && asset.mediaType === "image") || work.assets.find((asset) => asset.mediaType === "image");
    const shareUrl = window.location.href;

    return (
        <main className="min-h-screen bg-[#f7f8fa] text-[#20242a] dark:bg-[#0f1114] dark:text-[#f3f5f7]">
            <header className="sticky top-0 z-10 border-b border-black/5 bg-[#f7f8fa]/90 backdrop-blur dark:border-white/10 dark:bg-[#0f1114]/90">
                <div className="mx-auto flex h-14 w-full max-w-3xl items-center justify-between gap-3 px-4">
                    <button type="button" onClick={() => router.push("/agent")} className="inline-flex items-center gap-1.5 text-sm text-stone-600 hover:text-stone-900 dark:text-stone-300 dark:hover:text-stone-100">
                        <ArrowLeft className="size-4" />
                        返回
                    </button>
                    <div className="flex items-center gap-1.5 text-sm text-stone-500 dark:text-stone-400">
                        <Eye className="size-4" />
                        {work.viewCount} 次访问
                    </div>
                </div>
            </header>

            <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:py-10">
                {cover ? (
                    <section className="overflow-hidden rounded-xl border border-black/5 shadow-sm dark:border-white/10">
                        {cover.mediaType === "video" ? <video src={cover.url} className="max-h-[70vh] w-full bg-black object-contain" controls preload="metadata" /> : <img src={cover.url} alt={work.title} className="max-h-[70vh] w-full bg-black object-contain" />}
                    </section>
                ) : null}

                {work.assets.length > 1 ? (
                    <section className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {work.assets.map((asset) => {
                            if (cover && asset.id === cover.id) return null;
                            return (
                                <div key={asset.id} className="overflow-hidden rounded-lg border border-black/5 bg-black dark:border-white/10">
                                    {asset.mediaType === "video" ? (
                                        <video src={asset.url} className="aspect-[4/3] w-full object-cover" preload="metadata" muted />
                                    ) : asset.mediaType === "audio" ? (
                                        <div className="grid aspect-[4/3] w-full place-items-center bg-stone-100 dark:bg-stone-900">
                                            <Music2 className="size-6 text-stone-400" />
                                        </div>
                                    ) : (
                                        <img src={asset.url} alt={work.title} className="aspect-[4/3] w-full object-cover" loading="lazy" />
                                    )}
                                </div>
                            );
                        })}
                    </section>
                ) : null}

                <section className="mt-6">
                    <div className="flex items-center gap-1.5 text-xs text-stone-400 dark:text-stone-500">
                        {work.category ? <Tag className="m-0">{work.category}</Tag> : null}
                        {work.tags.slice(0, 6).map((tag) => (
                            <Tag key={tag} className="m-0">
                                {tag}
                            </Tag>
                        ))}
                    </div>
                    <h1 className="mt-2 text-2xl font-semibold leading-snug sm:text-3xl">{work.title}</h1>
                    {work.description ? <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-stone-600 dark:text-stone-300">{work.description}</p> : null}
                </section>

                <section className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-black/5 bg-white p-3 dark:border-white/10 dark:bg-[#15181d]">
                    <div className="flex min-w-0 items-center gap-2.5">
                        {work.authorAvatarUrl ? <img src={work.authorAvatarUrl} alt="" className="size-9 shrink-0 rounded-full object-cover" /> : <span className="grid size-9 shrink-0 place-items-center rounded-full bg-stone-200 text-xs font-semibold text-stone-600 dark:bg-stone-700 dark:text-stone-200">{work.authorName?.slice(0, 1) || "作"}</span>}
                        <div className="min-w-0">
                            <div className="truncate text-sm font-medium">{work.authorName || "匿名作者"}</div>
                            <div className="text-xs text-stone-400 dark:text-stone-500">{community ? `${community.followerCount} 位关注者` : "作者"}</div>
                        </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                        <Tooltip title="复制分享链接">
                            <Button size="small" icon={<Link2 className="size-3.5" />} onClick={() => copyText(shareUrl, "分享链接已复制")}>
                                分享
                            </Button>
                        </Tooltip>
                        {community?.canFollow ? (
                            <Button size="small" type={community.followingAuthor ? "default" : "primary"} icon={community.followingAuthor ? <UserCheck className="size-3.5" /> : <UserPlus className="size-3.5" />} onClick={() => void toggleFollow()}>
                                {community.followingAuthor ? "已关注" : "关注"}
                            </Button>
                        ) : null}
                        <Button size="small" type={community?.liked ? "primary" : "default"} icon={<Heart className={`size-3.5 ${community?.liked ? "fill-current" : ""}`} />} onClick={() => void toggleLike()}>
                            {community?.likeCount ?? work.likeCount}
                        </Button>
                    </div>
                </section>

                {work.publicPrompt ? (
                    <section className="mt-4 rounded-xl border border-black/5 bg-white p-4 dark:border-white/10 dark:bg-[#15181d]">
                        <div className="mb-2 flex items-center justify-between gap-2">
                            <div className="text-sm font-semibold">作品提示词</div>
                            <Button size="small" icon={<Copy className="size-3.5" />} onClick={() => copyText(work.publicPrompt, "提示词已复制")}>
                                复制
                            </Button>
                        </div>
                        <p className="whitespace-pre-wrap rounded-lg bg-stone-50 p-3 text-sm leading-6 text-stone-600 dark:bg-stone-900 dark:text-stone-300">{work.publicPrompt}</p>
                    </section>
                ) : null}

                <div className="mt-8 flex items-center justify-center gap-2 text-xs text-stone-400 dark:text-stone-500">
                    {work.sourceType === "drama" ? <Film className="size-3.5" /> : work.sourceType === "media" ? <ImageIcon className="size-3.5" /> : null}
                    作品发布于 {new Date(work.publishedAt).toLocaleString("zh-CN")}
                </div>
            </div>
        </main>
    );
}