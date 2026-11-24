export interface SiteListReturn {
  href: string;
  siteKey: string;
  scrollTop: number;
  from: string;
}

// A browser Back restores the original location entry rather than the site's state.
let lastDeparture: { key: string; position: SiteListReturn } | undefined;

export function rememberSiteList(key: string, position: SiteListReturn) {
  lastDeparture = { key, position };
  return { siteListReturn: position };
}

export function readSiteListReturn(
  state: unknown,
  batchPath: string,
): SiteListReturn | undefined {
  const position = (state as { siteListReturn?: Partial<SiteListReturn> } | null)
    ?.siteListReturn;
  if (
    position &&
    typeof position.href === "string" &&
    position.href.split("?")[0] === batchPath &&
    typeof position.siteKey === "string" &&
    typeof position.scrollTop === "number" &&
    Number.isFinite(position.scrollTop) &&
    position.scrollTop >= 0 &&
    typeof position.from === "string" &&
    /^\/batches(?:\?|$)/.test(position.from)
  )
    return position as SiteListReturn;
  return undefined;
}

export function takeSiteListDeparture(key: string) {
  if (lastDeparture?.key !== key) return;
  const { position } = lastDeparture;
  lastDeparture = undefined;
  return position;
}
