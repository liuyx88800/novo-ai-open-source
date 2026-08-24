import React from "react";
import { useNavigate, useParams as rrUseParams, useLocation, Link as RRLink, useSearchParams as rrUseSearchParams } from "react-router-dom";

export function useRouter() {
  const navigate = useNavigate();
  return {
    push: (href: string) => navigate(href),
    replace: (href: string) => navigate(href, { replace: true }),
    back: () => navigate(-1),
    forward: () => navigate(1),
    refresh: () => {},
    prefetch: () => {},
    query: {},
  };
}

export const useParams = rrUseParams;

export function useSearchParams() {
  const [params] = rrUseSearchParams();
  return params;
}

export function usePathname() {
  return useLocation().pathname;
}

export function dynamic(loader: () => Promise<{ default: React.ComponentType<unknown> }>, opts?: { ssr?: boolean; loading?: React.ComponentType<unknown> }) {
  const Lazy = React.lazy(loader as () => Promise<{ default: React.ComponentType<unknown> }>);
  const Loading = opts?.loading;
  return function DynamicWrapper(props: Record<string, unknown>) {
    return (
      <React.Suspense fallback={Loading ? <Loading /> : null}>
        <Lazy {...props} />
      </React.Suspense>
    );
  };
}

export function Link({ href, as, legacyBehavior, children, className, ...rest }: { href: string; as?: string; legacyBehavior?: boolean; children: React.ReactNode; className?: string }) {
  return (
    <RRLink to={href} className={className} {...rest}>
      {children}
    </RRLink>
  );
}

export default Link;
