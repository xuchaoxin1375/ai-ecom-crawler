const ABSOLUTE_HTTP = /^https?:\/\//i;

/**
 * Route an external image through the same-origin image endpoint so the
 * backend can apply the task or configured proxy. Data, blob and relative
 * URLs are already same-origin and must not be wrapped.
 */
export function imageProxyUrl(value: string, taskId?: string | null): string {
  if (!value || !ABSOLUTE_HTTP.test(value)) return value;
  const params = new URLSearchParams({ url: value });
  if (taskId) params.set("task_id", taskId);
  return `/api/media/image?${params.toString()}`;
}
