export interface Health {
  status: string;
  version: string;
  tasks: number;
  worker: string | null;
  max_tasks: number | null;
  rules_configured: boolean;
}

export interface TaskCounts {
  valid_products?: number;
  failed_products?: number;
  [key: string]: number | undefined;
}

export interface TaskSummary {
  task_id: string;
  task_type: string;
  state: string;
  outcome: string | null;
  counts: TaskCounts;
  updated_at: string;
}

export interface TaskPage {
  total: number;
  items: TaskSummary[];
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}

export function getTasks(): Promise<TaskPage> {
  return getJson<TaskPage>("/api/tasks?limit=20");
}
