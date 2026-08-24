"use client";

import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { ChevronRight, CreditCard, Crown, Keyboard, LogOut, ReceiptText, ShieldCheck, UserCircle, WalletCards } from "lucide-react";
import Link from "@/studio/next-shim";
import { useRouter } from "@/studio/next-shim";
import type { MenuProps } from "antd";
import { App, Button, Dropdown, Popover } from "antd";

import { AnimatedThemeToggler } from "@/components/ui/animated-theme-toggler";
import { AnnouncementNotificationCenter } from "@/components/layout/announcement-notification-center";
import { formatCreditAmount } from "@/constant/credits";
import { cn } from "@/lib/utils";
import { userAvatarFallback } from "@/lib/user-avatar";
import { studioPanelThemes } from "@/lib/panel-theme";
import { useThemeStore } from "@/stores/use-theme-store";
import { useUserStore, type LocalUser } from "@/stores/use-user-store";
import { resetClientSessionState } from "@/lib/client-session-reset";
import { loadPublicSession } from "@/stores/use-public-session-store";

type UserStatusActionsProps = {
    variant?: "default" | "canvas";
    onOpenShortcuts?: () => void;
    initialUser?: LocalUser;
};

function openNovoAccountCenter() {
    if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: "studio-open-page", page: "user-center" }, window.location.origin);
        return;
    }
    window.location.assign("/static/user-center.html");
}

export function UserStatusActions({ variant = "default", onOpenShortcuts, initialUser }: UserStatusActionsProps) {
    const router = useRouter();
    const { message } = App.useApp();
    const [pointsOpen, setPointsOpen] = useState(false);
    const [accountOpen, setAccountOpen] = useState(false);
    const [isCompactViewport, setIsCompactViewport] = useState(false);
    const rootRef = useRef<HTMLDivElement>(null);
    const storeUser = useUserStore((state) => state.user);
    const user = storeUser || initialUser || null;
    const theme = useThemeStore((state) => state.theme);
    const setTheme = useThemeStore((state) => state.setTheme);
    const canvasTheme = studioPanelThemes[theme];
    const defaultControlClass =
        "inline-flex h-8 shrink-0 items-center justify-center rounded-lg border border-[#e6e9ed] bg-white text-sm font-medium text-[#59616c] transition hover:border-[#d9dde3] hover:bg-[#f3f5f7] hover:text-[#20242a] dark:border-[#2c3138] dark:bg-[#181b20] dark:text-[#b7bec8] dark:hover:border-[#3b424c] dark:hover:bg-[#22262c] dark:hover:text-white";
    const canvasControlClass =
        "inline-flex h-9 shrink-0 items-center justify-center rounded-xl border px-2.5 text-sm font-medium shadow-sm transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/35 [&_svg]:size-4";
    const canvasIconClass = cn(canvasControlClass, "w-9 px-0");
    const canvasControlStyle: CSSProperties | undefined =
        variant === "canvas"
            ? {
                  background: canvasTheme.toolbar.panel,
                  borderColor: canvasTheme.toolbar.border,
                  boxShadow: theme === "dark" ? "0 10px 30px rgba(0,0,0,.28)" : "0 10px 24px rgba(28,25,23,.08)",
                  color: canvasTheme.toolbar.item,
              }
            : undefined;
    const naturalIconClass = variant === "canvas" ? canvasIconClass : cn(defaultControlClass, "w-8 px-0 [&_svg]:size-4");
    const iconStyle: CSSProperties | undefined = variant === "canvas" ? canvasControlStyle : undefined;
    const avatarUrl = user?.avatarUrl?.trim();
    const avatarFallback = userAvatarFallback(user?.displayName || user?.username || "用户");
    const accountName = user?.displayName || user?.username || "用户";
    const accountSecondary = user ? `ID：${user.accountId}` : "";
    const planActionLabel = user?.hasActivePlan ? "续费套餐" : "升级套餐";
    const accountItems: MenuProps["items"] = [
        {
            type: "group",
            label: (
                <div className="w-full py-0.5">
                    <div className="flex items-center gap-2.5">
                        {avatarUrl ? (
                            <img src={avatarUrl} alt="" className="size-9 rounded-lg object-cover" referrerPolicy="no-referrer" />
                        ) : (
                            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[#66758e] text-[11px] font-semibold text-white dark:bg-[#d8dee8] dark:text-[#252b33]">{avatarFallback}</span>
                        )}
                        <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-semibold text-stone-950 dark:text-stone-100">{accountName}</div>
                            {accountSecondary ? (
                                <div className="mt-0.5 truncate text-xs text-stone-400 dark:text-stone-500" title={accountSecondary}>
                                    {accountSecondary}
                                </div>
                            ) : null}
                        </div>
                    </div>
                    <div className="mt-2.5 rounded-lg border border-stone-200 bg-stone-50 p-2.5 dark:border-stone-800 dark:bg-stone-900/70">
                        <div className="flex items-center justify-between gap-3">
                            <div className="min-w-0">
                                <div className="text-[11px] text-stone-400 dark:text-stone-500">当前套餐</div>
                                <div className="mt-0.5 truncate text-sm font-semibold text-stone-900 dark:text-stone-100">{user?.planName || user?.planId || "免费版"}</div>
                            </div>
                            <button
                                type="button"
                                className="account-upgrade-button inline-flex h-7 shrink-0 items-center justify-center gap-1 rounded-md bg-stone-950 px-2.5 text-[11px] font-semibold transition hover:bg-black dark:bg-white dark:hover:bg-stone-100"
                                aria-label={planActionLabel}
                                title={planActionLabel}
                                onClick={(event) => {
                                    event.preventDefault();
                                    event.stopPropagation();
                                    setAccountOpen(false);
                                    openNovoAccountCenter();
                                }}
                            >
                                <Crown className="size-3.5" /> {planActionLabel}
                            </button>
                        </div>
                        <div className="mt-2 flex items-center justify-between gap-3 border-t border-stone-200 pt-2 text-xs dark:border-stone-800">
                            <span className="text-stone-500 dark:text-stone-400">账户余额</span>
                            <span className="inline-flex shrink-0 items-center gap-1.5 font-semibold text-stone-900 dark:text-stone-100">
                                <WalletCards className="size-3.5 text-[#66758e] dark:text-[#d8dee8]" />
                                ¥{formatCreditAmount(user?.pointsBalance || 0)}
                            </span>
                        </div>
                    </div>
                </div>
            ),
            children: [],
        },
        { type: "divider" },
        {
            key: "profile",
            icon: <UserCircle className="size-4" />,
            label: "个人中心",
        },
        {
            key: "billing",
            icon: <CreditCard className="size-4" />,
            label: "账户与充值",
        },
        ...(user?.role === "admin"
            ? [
                  { type: "divider" as const },
                  {
                      key: "admin",
                      icon: <ShieldCheck className="size-4" />,
                      label: (
                          <Link href="/admin" prefetch onMouseEnter={() => router.prefetch("/admin")} onFocus={() => router.prefetch("/admin")}>
                              管理员后台
                          </Link>
                      ),
                  },
              ]
            : []),
        { type: "divider" },
        {
            key: "logout",
            icon: <LogOut className="size-4" />,
            label: "退出登录",
            danger: true,
        },
    ];

    useEffect(() => {
        if (user?.role === "admin") router.prefetch("/admin");
        if (user) {
            router.prefetch("/canvas");
            router.prefetch("/profile");
        }
    }, [router, user]);

    useEffect(() => {
        const mediaQuery = window.matchMedia("(max-width: 520px)");
        const syncViewport = () => setIsCompactViewport(mediaQuery.matches);
        syncViewport();
        mediaQuery.addEventListener("change", syncViewport);
        return () => mediaQuery.removeEventListener("change", syncViewport);
    }, []);

    const handleMenuClick: MenuProps["onClick"] = async ({ key }) => {
        if (key === "profile" || key === "billing") {
            openNovoAccountCenter();
            return;
        }
        if (key !== "logout") return;
        try {
            await fetch("/api/auth/logout", { method: "POST" });
            await resetClientSessionState();
            router.replace("/login");
            router.refresh();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "退出登录失败");
        }
    };

    const handleAccountMenuClick: MenuProps["onClick"] = (info) => {
        setAccountOpen(false);
        void handleMenuClick(info);
    };

    useEffect(() => {
        if (variant !== "canvas" || (!pointsOpen && !accountOpen)) return;
        const closeCanvasPopups = (event: PointerEvent) => {
            const target = event.target;
            if (!(target instanceof Node)) return;
            if (rootRef.current?.contains(target)) return;
            if (target instanceof Element && target.closest(".user-points-popover, .ant-dropdown, .ant-dropdown-menu, .ant-dropdown-menu-submenu, .ant-dropdown-menu-submenu-popup")) {
                return;
            }
            setPointsOpen(false);
            setAccountOpen(false);
        };
        document.addEventListener("pointerdown", closeCanvasPopups, true);
        return () => document.removeEventListener("pointerdown", closeCanvasPopups, true);
    }, [variant, pointsOpen, accountOpen]);

    const handleAccountOpenChange = (open: boolean) => {
        setAccountOpen(open);
        if (open) setPointsOpen(false);
    };

    const pointsButton = user ? (
        <button
            type="button"
            className={cn(variant === "canvas" ? canvasControlClass : defaultControlClass, "gap-1 px-2 text-xs font-semibold sm:gap-1.5 sm:px-2.5", variant === "canvas" ? "canvas-points-action" : "app-points-action shrink-0")}
            style={iconStyle}
            title="账户余额"
        >
            <WalletCards className="size-3.5" />
            ¥{formatCreditAmount(user.pointsBalance)}
        </button>
    ) : null;

    return (
        <div ref={rootRef} className={cn("user-status-actions inline-flex max-w-full items-center gap-1.5 sm:gap-2", variant === "canvas" ? "canvas-user-status-actions shrink-0" : "app-user-status-actions min-w-0")}>
            {user ? (
                <Popover
                    rootClassName="user-points-popover"
                    open={pointsOpen}
                    onOpenChange={(open) => {
                        setPointsOpen(open);
                        if (open) setAccountOpen(false);
                    }}
                    trigger="click"
                    placement="bottomRight"
                    content={
                        <PointsSummaryPanel
                            user={user}
                            onClose={() => setPointsOpen(false)}
                            onManageAccount={() => {
                                setPointsOpen(false);
                                openNovoAccountCenter();
                            }}
                        />
                    }
                >
                    {pointsButton}
                </Popover>
            ) : null}
            <AnnouncementNotificationCenter
                compact={isCompactViewport}
                buttonClassName={cn(naturalIconClass, variant === "canvas" ? "canvas-notification-action" : "app-notification-action")}
                buttonStyle={iconStyle}
                onOpen={() => {
                    setPointsOpen(false);
                    setAccountOpen(false);
                }}
            />
            <AnimatedThemeToggler
                theme={theme}
                onThemeChange={setTheme}
                className={cn(naturalIconClass, variant === "canvas" && "canvas-theme-action")}
                style={iconStyle}
                aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
                title={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
            />
            {user ? (
                <>
                    <Dropdown rootClassName="account-menu-dropdown" open={accountOpen} onOpenChange={handleAccountOpenChange} menu={{ items: accountItems, onClick: handleAccountMenuClick }} trigger={["click"]} placement="bottomRight">
                        <button
                            type="button"
                            className={cn(
                                variant === "canvas" ? canvasControlClass : defaultControlClass,
                                variant === "canvas"
                                    ? "canvas-account-action size-9 rounded-full border-0 bg-transparent p-0 hover:bg-transparent"
                                    : "app-account-action size-8 rounded-full border-0 bg-transparent p-0 hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent",
                            )}
                            style={iconStyle}
                            aria-label="账户菜单"
                            title={user.displayName || user.username}
                        >
                            {avatarUrl ? (
                                <img src={avatarUrl} alt="" className="size-full rounded-full object-cover" referrerPolicy="no-referrer" />
                            ) : (
                                <span
                                    aria-hidden="true"
                                    className="user-avatar-fallback grid size-full place-items-center rounded-full bg-[#66758e] text-[11px] font-semibold leading-none text-white ring-1 ring-black/5 transition hover:bg-[#586983] dark:bg-[#d8dee8] dark:text-[#252b33] dark:ring-white/10 dark:hover:bg-white"
                                >
                                    {avatarFallback}
                                </span>
                            )}
                        </button>
                    </Dropdown>
                </>
            ) : (
                <Link href="/login" className={cn(variant === "canvas" ? canvasControlClass : defaultControlClass, "gap-2 px-2.5", variant === "canvas" && "canvas-account-action")} style={iconStyle}>
                    <UserCircle className="size-4" />
                    <span className="hidden sm:inline">登录</span>
                </Link>
            )}
            {onOpenShortcuts ? (
                <button type="button" className={cn(naturalIconClass, variant === "canvas" && "canvas-shortcuts-action")} style={iconStyle} onClick={onOpenShortcuts} aria-label="快捷键" title="快捷键">
                    <Keyboard className="size-4" />
                </button>
            ) : null}
        </div>
    );
}

function PointsSummaryPanel({ user, onClose, onManageAccount }: { user: LocalUser; onClose: () => void; onManageAccount: () => void }) {
    const setUser = useUserStore((state) => state.setUser);
    const [recordTotal, setRecordTotal] = useState<number>();
    useEffect(() => {
        let active = true;
        void Promise.all([loadPublicSession({ force: true }), fetch("/api/points?page=1&pageSize=1", { cache: "no-store" }).then((response) => response.json())])
            .then(([session, payload]: [{ user?: LocalUser | null }, { total?: number }]) => {
                if (!active) return;
                if (session.user) setUser(session.user);
                if (Number.isFinite(payload.total)) setRecordTotal(Number(payload.total));
            })
            .catch(() => undefined);
        return () => {
            active = false;
        };
    }, [setUser, user.id]);

    return (
        <div className="user-points-panel w-[min(19rem,calc(100vw-2rem))] text-stone-950 dark:text-stone-100">
            <div className="flex items-start justify-between gap-3 px-0.5 pb-2.5">
                <div className="min-w-0">
                    <div className="text-base font-semibold leading-6">账户余额</div>
                    <div className="mt-0.5 text-[11px] leading-4 text-stone-500 dark:text-stone-400">与 Novo AI 主账户同步，可用于全部创作服务</div>
                </div>
                <span className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-2.5 text-xs font-medium text-stone-600 dark:border-stone-800 dark:bg-stone-900/70 dark:text-stone-300">
                    <WalletCards className="size-3.5 text-stone-600 dark:text-stone-300" /> 可用 <strong className="text-sm tabular-nums text-stone-950 dark:text-stone-100">¥{formatCreditAmount(user.pointsBalance)}</strong>
                </span>
            </div>
            <div className="grid grid-cols-2 gap-2 border-y border-stone-200 py-2.5 dark:border-stone-800">
                <div className="rounded-lg bg-stone-50 px-3 py-2 dark:bg-stone-900/65">
                    <div className="text-[11px] text-stone-500 dark:text-stone-400">当前可用</div>
                    <strong className="mt-0.5 block text-base font-semibold tabular-nums">¥{formatCreditAmount(user.pointsBalance)}</strong>
                </div>
                <div className="rounded-lg bg-stone-50 px-3 py-2 dark:bg-stone-900/65">
                    <div className="text-[11px] text-stone-500 dark:text-stone-400">消费记录</div>
                    <strong className="mt-0.5 block text-base font-semibold tabular-nums">{recordTotal === undefined ? "--" : `${recordTotal} 条`}</strong>
                </div>
            </div>
            <Button
                block
                type="primary"
                icon={<WalletCards className="size-4" />}
                onClick={onManageAccount}
                className="points-summary-purchase !mt-2.5 !flex !h-11 !items-center !justify-center !gap-2 !rounded-xl !border-stone-950 !bg-stone-950 !px-3 !text-sm !font-semibold !text-stone-50 !shadow-none hover:!border-stone-800 hover:!bg-stone-800 hover:!text-stone-50 focus-visible:!ring-2 focus-visible:!ring-stone-400/50 dark:!border-stone-100 dark:!bg-stone-100 dark:!text-stone-950 dark:hover:!border-stone-200 dark:hover:!bg-stone-200 dark:hover:!text-stone-950"
            >
                充值与账户管理
            </Button>
            <button type="button" onClick={() => { onClose(); openNovoAccountCenter(); }} className="mt-1 flex min-h-11 w-full items-center justify-between rounded-lg px-2 text-sm font-medium text-stone-800 transition motion-reduce:transition-none hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400/50 dark:text-stone-100 dark:hover:bg-stone-800/80">
                <span className="inline-flex items-center gap-2"><ReceiptText className="size-4 text-stone-500" />查看消费明细</span>
                <ChevronRight className="size-4 text-stone-400" />
            </button>
        </div>
    );
}
